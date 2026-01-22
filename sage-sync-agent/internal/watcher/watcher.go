package watcher

import (
        "os"
        "path/filepath"
        "strings"
        "sync"
        "time"

        "github.com/dms/sage-sync-agent/internal/queue"
        "github.com/fsnotify/fsnotify"
        "github.com/rs/zerolog/log"
)

type Watcher struct {
        folder           string
        patterns         []string
        stabilitySeconds int
        queue            *queue.Queue

        pending     map[string]time.Time
        pendingLock sync.Mutex
        done        chan struct{}
}

func New(folder string, patterns []string, stabilitySeconds int, q *queue.Queue) *Watcher {
        if len(patterns) == 0 {
                patterns = []string{"*.pdf", "*.xlsx", "*.docx"}
        }
        if stabilitySeconds <= 0 {
                stabilitySeconds = 5
        }
        return &Watcher{
                folder:           folder,
                patterns:         patterns,
                stabilitySeconds: stabilitySeconds,
                queue:            q,
                pending:          make(map[string]time.Time),
                done:             make(chan struct{}),
        }
}

func (w *Watcher) Start() error {
        watcher, err := fsnotify.NewWatcher()
        if err != nil {
                return err
        }
        defer watcher.Close()

        if err := os.MkdirAll(w.folder, 0755); err != nil {
                return err
        }

        if err := watcher.Add(w.folder); err != nil {
                return err
        }

        log.Info().Str("folder", w.folder).Msg("Watching folder for new files")

        w.scanExisting()

        go w.stabilityChecker()

        for {
                select {
                case event, ok := <-watcher.Events:
                        if !ok {
                                return nil
                        }
                        w.handleEvent(event)
                case err, ok := <-watcher.Errors:
                        if !ok {
                                return nil
                        }
                        log.Error().Err(err).Msg("Watcher error")
                case <-w.done:
                        return nil
                }
        }
}

func (w *Watcher) Stop() {
        close(w.done)
}

func (w *Watcher) scanExisting() {
        entries, err := os.ReadDir(w.folder)
        if err != nil {
                log.Error().Err(err).Msg("Failed to scan existing files")
                return
        }

        for _, entry := range entries {
                if entry.IsDir() {
                        continue
                }
                path := filepath.Join(w.folder, entry.Name())
                if w.matchesPattern(entry.Name()) {
                        w.addToPending(path)
                }
        }
}

func (w *Watcher) handleEvent(event fsnotify.Event) {
        if event.Op&(fsnotify.Create|fsnotify.Write) == 0 {
                return
        }

        name := filepath.Base(event.Name)
        if !w.matchesPattern(name) {
                return
        }

        log.Debug().Str("file", event.Name).Str("op", event.Op.String()).Msg("File event")
        w.addToPending(event.Name)
}

func (w *Watcher) matchesPattern(name string) bool {
        for _, pattern := range w.patterns {
                matched, _ := filepath.Match(strings.ToLower(pattern), strings.ToLower(name))
                if matched {
                        return true
                }
        }
        return false
}

func (w *Watcher) addToPending(path string) {
        w.pendingLock.Lock()
        defer w.pendingLock.Unlock()
        w.pending[path] = time.Now()
}

func (w *Watcher) stabilityChecker() {
        ticker := time.NewTicker(time.Second)
        defer ticker.Stop()

        for {
                select {
                case <-ticker.C:
                        w.checkPending()
                case <-w.done:
                        return
                }
        }
}

func (w *Watcher) checkPending() {
        w.pendingLock.Lock()
        defer w.pendingLock.Unlock()

        threshold := time.Duration(w.stabilitySeconds) * time.Second
        now := time.Now()

        for path, lastSeen := range w.pending {
                if now.Sub(lastSeen) < threshold {
                        continue
                }

                if !isFileReady(path) {
                        w.pending[path] = now
                        continue
                }

                info, err := os.Stat(path)
                if err != nil {
                        log.Debug().Str("file", path).Err(err).Msg("File no longer exists")
                        delete(w.pending, path)
                        continue
                }

                if err := w.queue.Enqueue(path, info.Size()); err != nil {
                        log.Error().Err(err).Str("file", path).Msg("Failed to enqueue file")
                        continue
                }

                log.Info().Str("file", path).Int64("size", info.Size()).Msg("File queued for upload")
                delete(w.pending, path)
        }
}
