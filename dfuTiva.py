#!/usr/bin/env python
#-------------------------------------------------------------------------------
# Texas Instruments Tiva DFU wrapper protocol
#
# Brian Costabile (bcostabi@gmail.com)
# https://github.com/briancostabile/tiva-dfu.git
# This code is in the public domain
#-------------------------------------------------------------------------------
import usb.core
import usb.util
import struct
import sys
import time
import os
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from dfu import DfuRequest, dfuFindAll, DfuRequestDnload, DfuState, DfuStatus


class DfuRequestTivaQuery(DfuRequest):
    ID = 0x42
    def __init__(self):
        super().__init__("TIVA_QUERY", usb.util.CTRL_IN)
        self.bmRequest = self.ID
        self.wValue = 0x23
        self.wLength = 4
        return

class DfuResponseTivaQuery():
    MARKER = 0x4C4D
    VERSION = 0x0001
    def __init__(self, data):
        if data is None:
            self.valid = False
        else:
            self.usMarker  = (data[1] * 256) + data[0]
            self.usVersion = (data[3] * 256) + data[2]
            self.valid = (self.usMarker == self.MARKER) and (self.usVersion == self.VERSION)
        return

    def __str__(self):
        s = f"valid:{self.valid} usMarker:0x{self.usMarker:04X} usVersion:0x{self.usVersion:04X}"
        return s


class DfuTivaCmdProg(DfuRequestDnload):
    CMD_ID = 0x01
    def __init__(self, start, size):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, start, size))
        return


class DfuTivaCmdRead(DfuRequestDnload):
    CMD_ID = 0x02
    def __init__(self, start, size):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, start, size))
        return


class DfuTivaCmdCheck(DfuRequestDnload):
    CMD_ID = 0x03
    def __init__(self, start, size):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, start, size))
        return


class DfuTivaCmdErase(DfuRequestDnload):
    CMD_ID = 0x04
    def __init__(self, start, num):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHHH",self.CMD_ID, 0, start, num, 0))
        return


class DfuTivaCmdInfo(DfuRequestDnload):
    CMD_ID = 0x05
    def __init__(self):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, 0, 0))
        return


class DfuTivaCmdInfoRsp():
    SIZE = 20
    def __init__(self, data):
        self.flashBlockSize, \
        self.numFlashBlocks, \
        self.partInfo, \
        self.classInfo, \
        self.flashTop, \
        self.appStartAddr = struct.unpack("<HHLLLL", data)
        return

    def __str__(self):
        s = f"flashBlockSize:{self.flashBlockSize} "
        s += f"numFlashBlocks:{self.numFlashBlocks} "
        s += f"partInfo:0x{self.partInfo:08X} "
        s += f"classInfo:{self.classInfo:08X} "
        s += f"flashTop:0x{self.flashTop:08X} "
        s += f"appStartAddr:{self.appStartAddr:08X}"
        return s


class DfuTivaCmdBin(DfuRequestDnload):
    CMD_ID = 0x06
    def __init__(self, enable):
        super().__init__(0)
        self.flag = 0 if(enable) else 1
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, 0, 0))
        return


class DfuTivaCmdReset(DfuRequestDnload):
    CMD_ID = 0x07
    def __init__(self):
        super().__init__(0)
        self.packet = bytearray(struct.pack("<BBHL",self.CMD_ID, 0, 0, 0))
        return


class DfuDeviceTiva():
    def __init__(self, dev):
        self.dev = dev
        self.maxSize = self.dev.altDesc.wTransferSize

        # Clear any previous state/stauts
        status = dev.getStatus()
        print(status)
        dev.abort()
        status = dev.getStatus()
        print(status)

        info = self.getInfo()
        self.flashBlockSize = info.flashBlockSize
        self.numFlashBlocks = info.numFlashBlocks
        self.partInfo = info.partInfo
        self.classInfo = info.classInfo
        self.flashTop  = info.flashTop
        self.appStartAddr = info.appStartAddr

        self.flashStatus = {}
        self.flashStatusUpdate()

        self.image = None
        return

    def flashStatusUpdate(self):
        for blk in range(self.numFlashBlocks):
            self.dev.tunnelDnloadNoStatus(DfuTivaCmdCheck(blk, self.flashBlockSize))
            status = self.dev.getStatus()
            self.flashStatus[blk] = (status.bStatus == DfuStatus.OK)
        return

    def flashErase(self, statusCallback=None):
        percentComplete = 0
        for i in range(self.numFlashBlocks):
            self.dev.tunnelDnloadNoStatus(DfuTivaCmdErase(i, 1))
            status = self.dev.getStatus()
            while (status.bState != DfuState.DFU_IDLE):
                time.sleep((status.bwPollTimeout/100))
                status = self.dev.getStatus()
            percentComplete = ((i/self.numFlashBlocks) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)
        self.flashStatusUpdate()
        if statusCallback is not None: statusCallback(True, 100)
        return

    def getInfo(self):
        self.dev.tunnelDnload(DfuTivaCmdInfo())
        data = self.dev.upload(DfuTivaCmdInfoRsp.SIZE)
        rsp = DfuTivaCmdInfoRsp(data)
        return rsp

    def reset(self):
        self.dev.tunnelDnloadNoStatus(DfuTivaCmdReset())
        self.dev.getStatus()
        return

    def uploadPrefixEnable(self, enable):
        self.dev.tunnelDnload(DfuTivaCmdBin(enable))
        return

    def imageRead(self, statusCallback=None):
        offset = 0
        size = self.flashTop
        self.image = bytearray()

        self.uploadPrefixEnable(False)
        self.dev.tunnelDnload(DfuTivaCmdRead(offset, size))
        size += 8
        percentComplete = 0
        while size > 0:
            readSize = self.maxSize if (size > self.maxSize) else size
            self.image += bytearray(self.dev.upload(readSize))
            percentComplete = (((self.flashTop - size)/self.flashTop) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)
            size -= readSize

        # Remove 8byte header from first packet
        self.image = self.image[8:]

        return self.image

    def imageFlash(self, statusCallback=None):
        # put the programming command header in front of the raw image
        data = DfuTivaCmdProg(0, len(self.image)).packet
        data += self.image
        remain = len(data)
        #print(f"Flashing Image: {len(self.image)} bytes")
        wBlockNum = 0
        offset = 0
        ret = 0
        percentComplete = 0
        while (remain > 0) and ret is not None:
            writeSize = self.maxSize if (remain > self.maxSize) else remain
            #print(f"block[{wBlockNum:04}] len:{writeSize} total:{offset}", end='\r', flush=True)
            writeData = data[ offset : (offset + writeSize) ]
            ret = self.dev.dnload(wBlockNum, writeData)
            offset += writeSize
            remain -= writeSize
            wBlockNum += 1
            percentComplete = ((offset/len(data)) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)

        if ret is None:
            #print("Error while Flashing image")
            if statusCallback is not None: statusCallback(False, percentComplete)
        else:
            if statusCallback is not None: statusCallback(True, 100)
            # Get DFU state machine back to Idle
            status = self.dev.getStatus()
            self.dev.abort()
            status = self.dev.getStatus()
        return

    def dumpBinary(self, filename):
        with open(filename, "wb") as f:
             f.write(self.image)
        return

    def loadBinary(self, filename):
        self.image = bytearray()
        with open(filename, "rb") as f:
            self.image = f.read()
        print(f"Loaded {filename} {len(self.image)} bytes")
        return

    def loadElf(self, filename):
        self.image = bytearray(b'\xFF') * self.flashTop
        cnt = 0
        with open(filename, 'rb') as f:
            try:
                elfFile = ELFFile(f)
            except ELFError:
                return False

            # Find all segments contained in flash
            flashSegments = []
            segments = elfFile.iter_segments()
            for segment in segments:
                if (segment.header['p_paddr'] < self.flashTop):
                    flashSegments.append(segment)

            # Find all sections loaded from segments contained in flash
            sections = elfFile.iter_sections()
            for section in sections:
                # See if this section is loaded from a flash segment
                flashSeg = None
                for seg in flashSegments:
                    if seg.section_in_segment(section):
                        flashSeg = seg
                        break

                # Copy flashed sections into local image. May be offset (run_addr vs load_addr)
                if flashSeg is not None:
                    offset = flashSeg.header['p_vaddr'] - flashSeg.header['p_paddr']
                    addr = section.header['sh_addr']
                    data = section.data()
                    cnt += len(data)
                    #addrRun = flashSeg.header['p_vaddr']
                    #print(f"Adding Section load_addr:0x{(addr - offset):08X}-0x{((addr-offset)+len(data)):08X} run_addr:0x{addrRun:08X}-0x{addrRun+len(data):08X} name:{section.name}")
                    for i in range(len(data)):
                        self.image[(addr - offset) + i] = data[i]

        print(f"Loaded {filename} {cnt} bytes")
        return True


##
# Utility function to find all the Tiva USB devices in DFU mode
def dfuTivaFindAll():
    devices = dfuFindAll(vendorId=0x1CBE, productId=0x00FF)
    devs = []
    for dev in devices:
        ret = dev.send(DfuRequestTivaQuery())
        if (DfuResponseTivaQuery(ret).valid):
            devs.append(dev)
    return devs
