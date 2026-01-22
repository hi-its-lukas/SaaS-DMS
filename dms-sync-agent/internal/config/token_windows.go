//go:build windows

package config

import (
        "syscall"
        "unsafe"
)

const (
        credTypeDomainPassword = 2
        credPersistLocalMachine = 2
)

var (
        advapi32              = syscall.NewLazyDLL("advapi32.dll")
        procCredWriteW        = advapi32.NewProc("CredWriteW")
        procCredReadW         = advapi32.NewProc("CredReadW")
        procCredFree          = advapi32.NewProc("CredFree")
)

type credential struct {
        Flags              uint32
        Type               uint32
        TargetName         *uint16
        Comment            *uint16
        LastWritten        syscall.Filetime
        CredentialBlobSize uint32
        CredentialBlob     *byte
        Persist            uint32
        AttributeCount     uint32
        Attributes         uintptr
        TargetAlias        *uint16
        UserName           *uint16
}

const targetName = "DMSSyncAgent_Token"

func storeTokenWindows(token string) error {
        targetPtr, _ := syscall.UTF16PtrFromString(targetName)
        tokenBytes := []byte(token)

        cred := credential{
                Type:               credTypeDomainPassword,
                TargetName:         targetPtr,
                CredentialBlobSize: uint32(len(tokenBytes)),
                CredentialBlob:     &tokenBytes[0],
                Persist:            credPersistLocalMachine,
        }

        ret, _, err := procCredWriteW.Call(
                uintptr(unsafe.Pointer(&cred)),
                0,
        )
        if ret == 0 {
                return err
        }
        return nil
}

func getTokenWindows() (string, error) {
        targetPtr, _ := syscall.UTF16PtrFromString(targetName)
        var pcred *credential

        ret, _, err := procCredReadW.Call(
                uintptr(unsafe.Pointer(targetPtr)),
                uintptr(credTypeDomainPassword),
                0,
                uintptr(unsafe.Pointer(&pcred)),
        )
        if ret == 0 {
                return "", err
        }
        defer procCredFree.Call(uintptr(unsafe.Pointer(pcred)))

        blob := make([]byte, pcred.CredentialBlobSize)
        copy(blob, (*[1 << 20]byte)(unsafe.Pointer(pcred.CredentialBlob))[:pcred.CredentialBlobSize])
        
        return string(blob), nil
}
