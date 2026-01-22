package queue

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/rs/zerolog/log"
	bolt "go.etcd.io/bbolt"
)

var bucketName = []byte("pending_files")

type FileEntry struct {
	Path       string    `json:"path"`
	Size       int64     `json:"size"`
	QueuedAt   time.Time `json:"queued_at"`
	Retries    int       `json:"retries"`
	LastError  string    `json:"last_error,omitempty"`
	NextRetry  time.Time `json:"next_retry"`
}

type Queue struct {
	db *bolt.DB
}

func New(path string) (*Queue, error) {
	if path == "" {
		path = getDefaultQueuePath()
	}

	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return nil, err
	}

	db, err := bolt.Open(path, 0600, &bolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, err
	}

	err = db.Update(func(tx *bolt.Tx) error {
		_, err := tx.CreateBucketIfNotExists(bucketName)
		return err
	})
	if err != nil {
		db.Close()
		return nil, err
	}

	return &Queue{db: db}, nil
}

func (q *Queue) Close() error {
	return q.db.Close()
}

func (q *Queue) Enqueue(path string, size int64) error {
	entry := FileEntry{
		Path:      path,
		Size:      size,
		QueuedAt:  time.Now(),
		Retries:   0,
		NextRetry: time.Now(),
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}

	return q.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketName)
		return b.Put([]byte(path), data)
	})
}

func (q *Queue) Dequeue() (*FileEntry, error) {
	var entry *FileEntry
	now := time.Now()

	err := q.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketName)
		c := b.Cursor()

		for k, v := c.First(); k != nil; k, v = c.Next() {
			var e FileEntry
			if err := json.Unmarshal(v, &e); err != nil {
				continue
			}

			if e.NextRetry.After(now) {
				continue
			}

			entry = &e
			return nil
		}
		return nil
	})

	return entry, err
}

func (q *Queue) MarkComplete(path string) error {
	return q.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketName)
		return b.Delete([]byte(path))
	})
}

func (q *Queue) MarkFailed(path string, errMsg string) error {
	return q.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketName)
		data := b.Get([]byte(path))
		if data == nil {
			return fmt.Errorf("entry not found: %s", path)
		}

		var entry FileEntry
		if err := json.Unmarshal(data, &entry); err != nil {
			return err
		}

		entry.Retries++
		entry.LastError = errMsg
		entry.NextRetry = time.Now().Add(backoffDuration(entry.Retries))

		log.Warn().
			Str("file", path).
			Int("retries", entry.Retries).
			Time("next_retry", entry.NextRetry).
			Str("error", errMsg).
			Msg("Upload failed, scheduling retry")

		newData, err := json.Marshal(entry)
		if err != nil {
			return err
		}
		return b.Put([]byte(path), newData)
	})
}

func (q *Queue) Size() int {
	var count int
	q.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketName)
		count = b.Stats().KeyN
		return nil
	})
	return count
}

func backoffDuration(retries int) time.Duration {
	switch {
	case retries <= 1:
		return 5 * time.Second
	case retries == 2:
		return 10 * time.Second
	case retries == 3:
		return 30 * time.Second
	case retries == 4:
		return 60 * time.Second
	case retries <= 10:
		return 5 * time.Minute
	default:
		return 30 * time.Minute
	}
}

func getDefaultQueuePath() string {
	if os.Getenv("ProgramData") != "" {
		return filepath.Join(os.Getenv("ProgramData"), "SageSyncAgent", "queue.db")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".sage-sync-agent", "queue.db")
}
