//go:build !windows

package watcher

func isFileReadyWindows(path string) bool {
	return isFileReadyUnix(path)
}
