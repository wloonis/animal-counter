# PRD: Jetson Orin Splash Screen on Startup

## Overview
Display a full-screen splash screen background image at Jetson Orin startup to mask the Linux desktop. This splash screen will automatically disappear when the k3s service 'countingapp' reaches the 'running' state.

## Context
- **Purpose**: Provide a clean, branded startup experience by hiding the Linux desktop during boot
- **Related System**: The animal-counter application runs as 'countingapp' service on k3s, deployed on the Jetson Orin
- **Trigger**: Once k3s reports 'countingapp' as running, the splash screen can be dismissed

## Tasks

- [ ] **Task 1**: Prepare splash screen image (1920x1080 or matching display resolution)
- [ ] **Task 2**: Create XDG autostart desktop entry for splash screen
- [ ] **Task 3**: Implement splash display script using feh or similar image viewer
- [ ] **Task 4**: Create k3s service monitoring script (polls countingapp status)
- [ ] **Task 5**: Add kill logic to hide splash when service is running
- [ ] **Task 6**: Add logging for debugging startup issues

## Files to Create
- [ ] `~/.config/autostart/splash-screen.desktop` - XDG autostart entry
- [ ] `~/scripts/splash-screen.sh` - Main splash display & monitoring script
- [ ] `~/scripts/splash-image.png` - Splash screen image

## Acceptance Criteria
- [ ] Splash screen displays in full screen mode immediately after X session starts
- [ ] Linux desktop is completely obscured during splash screen display
- [ ] Script polls k3s countingapp service status every 5 seconds
- [ ] Splash screen process is terminated when service state = "Running"
- [ ] System works reliably on Jetson Orin with Ubuntu desktop