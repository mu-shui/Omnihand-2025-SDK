// Copyright (c) 2025, Agibot Co., Ltd.
// OmniHand 2025 SDK is licensed under Mulan PSL v2.

/**
 * @file c_zlg_usbcanfd_sdk.h
 * @brief
 * @author WSJ
 * @date 25-7-28
 **/

#pragma once

#include "../c_can_bus_device.h"
#include <map>
#include <mutex>

/**
 * @brief 基于周立功usbcanfd的SDK的CAN Device类
 * 支持同一设备的多通道使用（设备只打开一次，每个通道独立初始化）
 */
class ZlgUsbcanfdSDK : public CanBusDeviceBase {
 public:
  ZlgUsbcanfdSDK(unsigned char canfd_id = 0, unsigned char channel_id = 0);

  ~ZlgUsbcanfdSDK() override;

  int OpenDevice() override;

  int CloseDevice() override;

  void RecvFrame() override;

  int SendFrame(unsigned int id, unsigned char* data, unsigned char length) override;

  bool IsInit() override;

 private:
  unsigned char canfd_id_;
  unsigned char channel_id_;

  // 静态设备管理：跟踪每个设备的打开状态和引用计数
  static std::mutex device_mutex_;
  static std::map<unsigned char, int> device_ref_count_;  // canfd_id -> 引用计数
};
