package uploader

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/dms/sage-sync-agent/internal/queue"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/rs/zerolog/log"
)

type Uploader struct {
	dmsURL          string
	token           string
	processedFolder string
	client          *http.Client
	done            chan struct{}
}

func New(dmsURL, token, processedFolder string) *Uploader {
	retryClient := retryablehttp.NewClient()
	retryClient.RetryMax = 3
	retryClient.RetryWaitMin = 1 * time.Second
	retryClient.RetryWaitMax = 10 * time.Second
	retryClient.Logger = nil

	return &Uploader{
		dmsURL:          dmsURL,
		token:           token,
		processedFolder: processedFolder,
		client:          retryClient.StandardClient(),
		done:            make(chan struct{}),
	}
}

func (u *Uploader) Start(q *queue.Queue) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			u.processQueue(q)
		case <-u.done:
			return
		}
	}
}

func (u *Uploader) Stop() {
	close(u.done)
}

func (u *Uploader) processQueue(q *queue.Queue) {
	entry, err := q.Dequeue()
	if err != nil {
		log.Error().Err(err).Msg("Failed to dequeue")
		return
	}
	if entry == nil {
		return
	}

	log.Info().Str("file", entry.Path).Msg("Processing file")

	if err := u.uploadFile(entry.Path); err != nil {
		q.MarkFailed(entry.Path, err.Error())
		return
	}

	if err := u.moveToProcessed(entry.Path); err != nil {
		log.Error().Err(err).Str("file", entry.Path).Msg("Failed to move to processed")
	}

	q.MarkComplete(entry.Path)
	log.Info().Str("file", entry.Path).Msg("Upload successful")
}

func (u *Uploader) uploadFile(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("failed to open file: %w", err)
	}
	defer file.Close()

	hash, err := computeHash(path)
	if err != nil {
		return fmt.Errorf("failed to compute hash: %w", err)
	}

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	part, err := writer.CreateFormFile("file", filepath.Base(path))
	if err != nil {
		return fmt.Errorf("failed to create form file: %w", err)
	}

	if _, err := io.Copy(part, file); err != nil {
		return fmt.Errorf("failed to copy file content: %w", err)
	}

	writer.WriteField("sha256", hash)
	writer.WriteField("source", "sage-sync-agent")
	writer.Close()

	url := fmt.Sprintf("%s/api/v1/ingest/document/", u.dmsURL)
	req, err := http.NewRequest("POST", url, &body)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-DMS-Token", u.token)

	resp, err := u.client.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusConflict {
		log.Info().Str("file", path).Msg("File already exists (duplicate)")
		return nil
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("upload failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	return nil
}

func (u *Uploader) moveToProcessed(path string) error {
	if u.processedFolder == "" {
		return nil
	}

	if err := os.MkdirAll(u.processedFolder, 0755); err != nil {
		return err
	}

	baseName := filepath.Base(path)
	timestamp := time.Now().Format("20060102_150405")
	newName := fmt.Sprintf("%s_%s", timestamp, baseName)
	destPath := filepath.Join(u.processedFolder, newName)

	return os.Rename(path, destPath)
}

func computeHash(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}

	return hex.EncodeToString(h.Sum(nil)), nil
}

func (u *Uploader) StartHeartbeat(intervalSeconds int, version string) {
	if intervalSeconds <= 0 {
		intervalSeconds = 300
	}

	ticker := time.NewTicker(time.Duration(intervalSeconds) * time.Second)
	defer ticker.Stop()

	u.sendHeartbeat(version, 0)

	for {
		select {
		case <-ticker.C:
			u.sendHeartbeat(version, 0)
		case <-u.done:
			return
		}
	}
}

func (u *Uploader) sendHeartbeat(version string, queueSize int) {
	payload := map[string]interface{}{
		"version":    version,
		"status":     "running",
		"queue_size": queueSize,
	}

	data, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/api/v1/agent/heartbeat/", u.dmsURL)

	req, err := http.NewRequest("POST", url, bytes.NewReader(data))
	if err != nil {
		log.Debug().Err(err).Msg("Failed to create heartbeat request")
		return
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-DMS-Token", u.token)

	resp, err := u.client.Do(req)
	if err != nil {
		log.Debug().Err(err).Msg("Heartbeat failed")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		log.Debug().Msg("Heartbeat sent")
	}
}
