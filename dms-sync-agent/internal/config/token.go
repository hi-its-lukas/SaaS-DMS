package config

import (
        "errors"
        "os"
        "path/filepath"
        "runtime"
)

func StoreToken(token string) error {
        if runtime.GOOS == "windows" {
                return storeTokenWindows(token)
        }
        return storeTokenFile(token)
}

func GetToken() (string, error) {
        if runtime.GOOS == "windows" {
                token, err := getTokenWindows()
                if err == nil && token != "" {
                        return token, nil
                }
        }
        return getTokenFile()
}

func storeTokenFile(token string) error {
        path := getTokenFilePath()
        os.MkdirAll(filepath.Dir(path), 0700)
        return os.WriteFile(path, []byte(token), 0600)
}

func getTokenFile() (string, error) {
        path := getTokenFilePath()
        data, err := os.ReadFile(path)
        if err != nil {
                return "", err
        }
        if len(data) == 0 {
                return "", errors.New("token file is empty")
        }
        return string(data), nil
}

func getTokenFilePath() string {
        if runtime.GOOS == "windows" {
                return filepath.Join(os.Getenv("ProgramData"), "DMSSyncAgent", ".token")
        }
        return filepath.Join(os.Getenv("HOME"), ".dms-sync-agent", ".token")
}
