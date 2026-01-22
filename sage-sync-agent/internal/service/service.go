package service

import (
	"fmt"

	"github.com/dms/sage-sync-agent/internal/config"
	"github.com/kardianos/service"
	"github.com/rs/zerolog/log"
)

type program struct {
	cfg     *config.Config
	run     func() error
	stopCh  chan struct{}
}

func (p *program) Start(s service.Service) error {
	p.stopCh = make(chan struct{})
	go func() {
		if err := p.run(); err != nil {
			log.Error().Err(err).Msg("Agent error")
		}
	}()
	return nil
}

func (p *program) Stop(s service.Service) error {
	close(p.stopCh)
	return nil
}

type Service struct {
	svc service.Service
	prg *program
}

func New(cfg *config.Config, run func() error) *Service {
	prg := &program{
		cfg: cfg,
		run: run,
	}

	svcConfig := &service.Config{
		Name:        "SageSyncAgent",
		DisplayName: "Sage Sync Agent",
		Description: "Monitors Sage export folder and uploads documents to DMS",
	}

	svc, _ := service.New(prg, svcConfig)

	return &Service{
		svc: svc,
		prg: prg,
	}
}

func (s *Service) Run() error {
	return s.svc.Run()
}

func (s *Service) Install() error {
	return s.svc.Install()
}

func (s *Service) Uninstall() error {
	s.svc.Stop()
	return s.svc.Uninstall()
}

func (s *Service) Start() error {
	return s.svc.Start()
}

func (s *Service) Stop() error {
	return s.svc.Stop()
}

func (s *Service) Status() (string, error) {
	status, err := s.svc.Status()
	if err != nil {
		return "", err
	}

	switch status {
	case service.StatusRunning:
		return "Running", nil
	case service.StatusStopped:
		return "Stopped", nil
	default:
		return fmt.Sprintf("Unknown (%d)", status), nil
	}
}
