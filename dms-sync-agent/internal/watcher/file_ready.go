package watcher

import (
	"os"
	"runtime"
)

func isFileReady(path string) bool {
	if runtime.GOOS == "windows" {
		return isFileReadyWindows(path)
	}
	return isFileReadyUnix(path)
}

func isFileReadyUnix(path string) bool {
	f, err := os.OpenFile(path, os.O_RDONLY, 0)
	if err != nil {
		return false
	}
	f.Close()
	return true
}
