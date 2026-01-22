package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/dms/sage-sync-agent/internal/config"
	"github.com/dms/sage-sync-agent/internal/queue"
	"github.com/dms/sage-sync-agent/internal/service"
	"github.com/dms/sage-sync-agent/internal/uploader"
	"github.com/dms/sage-sync-agent/internal/watcher"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

var (
	Version   = "1.0.0"
	BuildTime = "unknown"
)

func main() {
	install := flag.Bool("install", false, "Install as Windows service")
	uninstall := flag.Bool("uninstall", false, "Uninstall Windows service")
	start := flag.Bool("start", false, "Start the Windows service")
	stop := flag.Bool("stop", false, "Stop the Windows service")
	status := flag.Bool("status", false, "Show service status")
	configPath := flag.String("config", "", "Path to config file")
	setToken := flag.String("set-token", "", "Set API token securely")
	showVersion := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *showVersion {
		fmt.Printf("Sage Sync Agent v%s (Build: %s)\n", Version, BuildTime)
		os.Exit(0)
	}

	cfgPath := *configPath
	if cfgPath == "" {
		exe, _ := os.Executable()
		cfgPath = filepath.Join(filepath.Dir(exe), "config.yaml")
	}

	cfg, err := config.Load(cfgPath)
	if err != nil && !*install {
		fmt.Fprintf(os.Stderr, "Config error: %v\n", err)
		os.Exit(1)
	}

	setupLogging(cfg)

	if *setToken != "" {
		if err := config.StoreToken(*setToken); err != nil {
			log.Fatal().Err(err).Msg("Failed to store token")
		}
		log.Info().Msg("Token stored securely")
		os.Exit(0)
	}

	svc := service.New(cfg, func() error {
		return runAgent(cfg)
	})

	switch {
	case *install:
		if err := svc.Install(); err != nil {
			log.Fatal().Err(err).Msg("Failed to install service")
		}
		log.Info().Msg("Service installed successfully")
	case *uninstall:
		if err := svc.Uninstall(); err != nil {
			log.Fatal().Err(err).Msg("Failed to uninstall service")
		}
		log.Info().Msg("Service uninstalled successfully")
	case *start:
		if err := svc.Start(); err != nil {
			log.Fatal().Err(err).Msg("Failed to start service")
		}
		log.Info().Msg("Service started")
	case *stop:
		if err := svc.Stop(); err != nil {
			log.Fatal().Err(err).Msg("Failed to stop service")
		}
		log.Info().Msg("Service stopped")
	case *status:
		s, err := svc.Status()
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to get status")
		}
		fmt.Println(s)
	default:
		if err := svc.Run(); err != nil {
			log.Fatal().Err(err).Msg("Service failed")
		}
	}
}

func setupLogging(cfg *config.Config) {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix

	logPath := cfg.LogPath
	if logPath == "" {
		logPath = filepath.Join(os.Getenv("ProgramData"), "SageSyncAgent", "logs")
	}
	os.MkdirAll(logPath, 0755)

	logFile, err := os.OpenFile(
		filepath.Join(logPath, "agent.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND,
		0644,
	)
	if err != nil {
		log.Logger = zerolog.New(os.Stderr).With().Timestamp().Logger()
		log.Warn().Err(err).Msg("Could not open log file, using stderr")
	} else {
		log.Logger = zerolog.New(logFile).With().Timestamp().Logger()
	}
}

func runAgent(cfg *config.Config) error {
	log.Info().
		Str("version", Version).
		Str("watch_folder", cfg.WatchFolder).
		Str("dms_url", cfg.DMSURL).
		Msg("Starting Sage Sync Agent")

	token, err := config.GetToken()
	if err != nil {
		return fmt.Errorf("no API token configured: %w", err)
	}

	q, err := queue.New(cfg.QueuePath)
	if err != nil {
		return fmt.Errorf("failed to initialize queue: %w", err)
	}
	defer q.Close()

	up := uploader.New(cfg.DMSURL, token, cfg.ProcessedFolder)
	w := watcher.New(cfg.WatchFolder, cfg.IncludePatterns, cfg.StabilitySeconds, q)

	go up.Start(q)
	go up.StartHeartbeat(cfg.HeartbeatInterval, Version)

	return w.Start()
}
