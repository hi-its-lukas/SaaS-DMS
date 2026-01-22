package config

import (
	"errors"
	"os"

	"gopkg.in/yaml.v3"
)

type Config struct {
	DMSURL            string   `yaml:"dms_url"`
	WatchFolder       string   `yaml:"watch_folder"`
	ProcessedFolder   string   `yaml:"processed_folder"`
	TenantCode        string   `yaml:"tenant_code"`
	IncludePatterns   []string `yaml:"include_patterns"`
	QueuePath         string   `yaml:"queue_path"`
	LogPath           string   `yaml:"log_path"`
	StabilitySeconds  int      `yaml:"stability_seconds"`
	HeartbeatInterval int      `yaml:"heartbeat_interval_seconds"`
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return defaultConfig(), nil
		}
		return nil, err
	}

	cfg := defaultConfig()
	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	if cfg.WatchFolder == "" {
		return nil, errors.New("watch_folder is required")
	}
	if cfg.DMSURL == "" {
		return nil, errors.New("dms_url is required")
	}

	return cfg, nil
}

func defaultConfig() *Config {
	return &Config{
		DMSURL:            "https://portal.personalmappe.cloud",
		IncludePatterns:   []string{"*.pdf", "*.xlsx", "*.docx"},
		QueuePath:         "",
		LogPath:           "",
		StabilitySeconds:  5,
		HeartbeatInterval: 300,
	}
}

func Save(cfg *Config, path string) error {
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}
