#!/usr/bin/env python
# -------------------------------------------------------------------------------
# Generic DFU protocol
#
# Brian Costabile (bcostabi@gmail.com)
# https://github.com/briancostabile/tiva-dfu.git
# This code is in the public domain
# -------------------------------------------------------------------------------
import struct
import time
from enum import Enum

import usb.core
import usb.util


class DfuState(Enum):
    APP_IDLE = 0x00
    APP_DETACH = 0x01
    DFU_IDLE = 0x02
    DFU_DNLOAD_SYNC = 0x03
    DFU_DNLOAD_BUSY = 0x04
    DFU_MANIFEST_IDLE = 0x05
    DFU_MANIFEST_SYNC = 0x06
    DFU_MANIFEST = 0x07
    DFU_MANIFEST_WAIT_RESET = 0x08
    DFU_UPLOAD_IDLE = 0x09
    DFU_ERROR = 0x0A


class DfuStatus(Enum):
    OK = 0x00
    ERR_TARGET = 0x01
    ERR_FILE = 0x02
    ERR_WRITE = 0x03
    ERR_ERASE = 0x04
    ERR_CHECK_ERASED = 0x05
    ERR_PROG = 0x06
    ERR_VERIFY = 0x07
    ERR_ADDRESS = 0x08
    ERR_NOT_DONE = 0x09
    ERR_FIRMWARE = 0x0A
    ERR_VENDOR = 0x0B
    ERR_USBR = 0x0C
    ERR_POR = 0x0D
    ERR_UNKNOWN = 0x0E
    ERR_STALLED_PKT = 0x0F


class DfuRequest:
    def __init__(self, name, dir):
        self.name = name
        self.bmRequest = -1
        self.dir = dir
        self.type = usb.util.CTRL_TYPE_CLASS
        self.receiver = usb.util.CTRL_RECIPIENT_INTERFACE
        self.bmRequestType = self.dir | self.type | self.receiver
        self.wValue = 0
        self.wLength = 0
        self.packet = bytearray()
        return

    def __str__(self):
        s = f"{self.name}:\n"
        s += f"bmRequest:0x{self.bmRequest:02X}\n"
        s += f"\tdir:{self.dir}\n"
        s += f"\ttype:{self.type}\n"
        s += f"\treceiver:{self.receiver}\n"
        s += f"\tbmRequestType:0x{self.bmRequestType:02X}\n"
        s += f"\tpacket:{self.packet}"
        return s


class DfuRequestDetach(DfuRequest):
    ID = 0

    def __init__(self, wValue):
        super().__init__("DETACH", usb.util.CTRL_OUT)
        self.bmRequest = self.ID
        self.wValue = wValue
        return


class DfuRequestDnload(DfuRequest):
    ID = 1

    def __init__(self, wValue):
        super().__init__("DNLOAD", usb.util.CTRL_OUT)
        self.bmRequest = self.ID
        self.wValue = wValue
        return


class DfuRequestUpload(DfuRequest):
    ID = 2

    def __init__(self, wLength):
        super().__init__("UPLOAD", usb.util.CTRL_IN)
        self.bmRequest = self.ID
        self.wLength = wLength
        return


class DfuRequestGetStatus(DfuRequest):
    ID = 3

    def __init__(self):
        super().__init__("GETSTATUS", usb.util.CTRL_IN)
        self.bmRequest = self.ID
        self.wLength = 6
        return


class DfuResponseStatus:
    def __init__(self, data):
        self.bStatus = DfuStatus(data[0])
        self.bwPollTimeout = (data[3] << 16) + (data[2] << 8) + data[1]
        self.bState = DfuState(data[4])
        self.iString = data[5]
        return

    def __str__(self):
        s = f"bStatus:{self.bStatus} bwPollTimeout:{self.bwPollTimeout}ms bState:{self.bState}"
        return s


class DfuRequestClrStatus(DfuRequest):
    ID = 4

    def __init__(self):
        super().__init__("CLRSTATUS", usb.util.CTRL_OUT)
        self.bmRequest = self.ID
        return


class DfuRequestGetState(DfuRequest):
    ID = 5

    def __init__(self):
        super().__init__("GETSTATE", usb.util.CTRL_IN)
        self.bmRequest = self.ID
        self.wLength = 1
        return


class DfuResponseState:
    def __init__(self, data):
        self.bState = DfuState(data[0])
        return

    def __str__(self):
        s = f"bState:{self.bState}"
        return s


class DfuRequestAbort(DfuRequest):
    ID = 6

    def __init__(self):
        super().__init__("ABORT", usb.util.CTRL_OUT)
        self.bmRequest = self.ID
        return


class DfuFunctionalDescriptor:
    LENGTH = 9
    TYPE = 0x21

    def __init__(self, data):
        data = bytearray(data)
        self.valid = False

        if len(data) < 2:
            return

        self.bLength, self.bDescriptorType = struct.unpack("<BB", data[:2])
        if (self.bLength == self.LENGTH) and (self.bDescriptorType == self.TYPE):
            self.valid = True
            (
                self.bmAttributes,
                self.wDetachTimeOut,
                self.wTransferSize,
                self.bcdDFUVersion,
            ) = struct.unpack("<BHHH", data[2:])
            self.version = (
                f"{(self.bcdDFUVersion>>8)}.{((self.bcdDFUVersion>>4) & 0x0F)}"
            )
            self.willDetach = ((self.bmAttributes >> 3) & 0x01) != 0
            self.manifestationTolerant = ((self.bmAttributes >> 2) & 0x01) != 0
            self.canUpload = ((self.bmAttributes >> 1) & 0x01) != 0
            self.canDnload = ((self.bmAttributes >> 0) & 0x01) != 0
        return

    def detachTimeout(self):
        return self.wDetachTimeOut

    def transferSize(self):
        return self.wTransferSize

    def __str__(self):
        if self.valid:
            s = f"len:{self.bLength} type:{ self.bDescriptorType}\n"
            s += f"\taddtibutes:0x{self.bmAttributes:02X} willDetach:{self.willDetach} manifestationTolerant:{self.manifestationTolerant} canUpload:{self.canUpload} canDnload:{self.canDnload}\n"
            s += f"\tdetachTimeout:{self.wDetachTimeOut}\n\ttransferSize:{self.wTransferSize}\n\tbcdVer:{self.version}"
        else:
            s = "Invalid DFU"
        return s


class DfuDevice:
    TIMEOUT_MS = 2000

    def __init__(self, usbDev, usbCfg, usbIntf, altName, altDesc):
        self.usbDev = usbDev
        self.usbCfg = usbCfg
        self.usbIntf = usbIntf
        self.altName = altName
        self.altDesc = altDesc
        return

    def send(self, msg):
        if len(msg.packet) > 0:
            dataOrLen = msg.packet
        else:
            dataOrLen = msg.wLength
        try:
            ret = self.usbDev.ctrl_transfer(
                msg.bmRequestType,
                msg.bmRequest,
                wValue=msg.wValue,
                wIndex=self.usbIntf.iInterface,
                data_or_wLength=dataOrLen,
                timeout=self.TIMEOUT_MS,
            )
        except usb.core.USBError:
            ret = None

        return ret

    def detach(self, timeout):
        self.send(DfuRequestDetach(timeout))
        return

    def dnload(self, wBlockNum, data):
        req = DfuRequestDnload(wBlockNum)
        req.wLength = len(data)
        req.packet = data
        ret = self.send(req)
        if ret is not None:
            status = self.getStatus()
            while (status.bStatus != DfuStatus.OK) or (
                status.bState == DfuState.DFU_DNLOAD_SYNC
            ):
                time.sleep(status.bwPollTimeout / 1000)
                status = self.getStatus()
        return ret

    def upload(self, wLength):
        ret = self.send(DfuRequestUpload(wLength))
        return ret

    def getStatus(self):
        ret = self.send(DfuRequestGetStatus())
        rsp = None
        if ret is not None:
            rsp = DfuResponseStatus(ret)
            if rsp.bStatus != DfuStatus.OK:
                self.clrStatus()
        return rsp

    def clrStatus(self):
        self.send(DfuRequestClrStatus())
        return

    def getState(self):
        ret = self.send(DfuRequestGetState())
        rsp = DfuResponseState(ret)
        return rsp

    def abort(self):
        self.send(DfuRequestAbort())
        return

    def tunnelDnload(self, msg):
        self.send(msg)
        status = self.getStatus()
        while status.bStatus != DfuStatus.OK:
            time.sleep(status.bwPollTimeout / 1000)
            status = self.getStatus()
        return

    def tunnelDnloadNoStatus(self, msg):
        self.send(msg)
        return


def dfuFindAll(vendorId=None, productId=None):
    dfuDevices = []
    devs = usb.core.find(find_all=True)
    if devs is not None:
        for dev in devs:
            if ((vendorId is not None) and (vendorId != dev.idVendor)) or (
                (productId is not None) and (productId != dev.idProduct)
            ):
                continue

            configs = dev.configurations()
            for config in configs:
                # One functional descriptor can belong to multiple interfaces if they
                # are alternates of the same interface number

                # First find all interfaces with extra descriptors and map those to the
                # interface
                funcDict = {}
                for intf in config:
                    d = DfuFunctionalDescriptor(intf.extra_descriptors)
                    if d.valid:
                        funcDict[intf.bInterfaceNumber] = d

                for intf in config:
                    if intf.bInterfaceClass == 0xFE:  # Application Specific
                        if intf.bInterfaceNumber in funcDict.keys():
                            name = usb.util.get_string(dev, intf.iInterface)
                            name = "UNKNOWN" if (name is None) else name
                            dfuDevices.append(
                                DfuDevice(
                                    dev,
                                    config,
                                    intf,
                                    name,
                                    funcDict[intf.bInterfaceNumber],
                                )
                            )

    return dfuDevices
