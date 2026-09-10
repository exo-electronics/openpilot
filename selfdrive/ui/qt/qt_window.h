#pragma once

#include <string>

#include <QApplication>
#include <QScreen>
#include <QWidget>

// QCOM2-specific Wayland includes removed - Rockchip uses standard display
// TODO: Add Rockchip-specific display handling if needed

#include "system/hardware/hw.h"

const QString ASSET_PATH = ":/";

// ExoPilot 01M panel size. This branch targets 01M (RK3588) only -- 02M
// moved to VisionPilot's dev/02M line (docs/eop/BRANCH_NAMING.md), taking
// the wide-screen telemetry panel and its per-unit width param with it, so
// there is no longer any platform on which the screen differs from this.
constexpr int EOP_01M_WIDTH = 1024;
constexpr int EOP_01M_HEIGHT = 600;

inline QSize deviceScreenSize() {
  return {EOP_01M_WIDTH, EOP_01M_HEIGHT};
}

void setMainWindow(QWidget *w);
