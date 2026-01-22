//go:build !windows

package config

func storeTokenWindows(token string) error {
	return storeTokenFile(token)
}

func getTokenWindows() (string, error) {
	return getTokenFile()
}
