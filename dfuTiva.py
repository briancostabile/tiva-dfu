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

# Example Custom manufacturing structure at the end of flash
class MfgFmt1():
    SIGNATURE = 0x616c7545
    FMT = 1
    BSP_LEN = 24
    LEN = BSP_LEN + 8
    def __init__(self, productId='None', serialNum=0, rand0=None, rand1=None, data=None):
        if data is not None:
            self.mfgData = data

            (
                self.rand0,
                self.rand1,
                self.productId,
                self.serialNum,
                self.usrLen,
                self.bspLen,
                self.rsv,
                self.fmt,
                self.signature
             ) = struct.unpack("<QQLLBBBBL", self.mfgData)

            self.valid = (self.signature == self.SIGNATURE) and \
                         (self.fmt == self.FMT) and \
                         (self.rsv == 0) and \
                         (self.bspLen == self.BSP_LEN) and \
                         (self.usrLen == 0)
        else:
            self.valid = True
            self.rand0 = rand0
            self.rand1 = rand1
            self.productId = productId
            self.serialNum = serialNum
            self.usrLen = 0
            self.bspLen = self.BSP_LEN
            self.rsv = 0
            self.fmt = self.FMT
            self.signature = self.SIGNATURE
            self.rand0 = rand0 if rand0 is not None else int.from_bytes(os.urandom(8), "little", signed=False)
            self.rand1 = rand1 if rand1 is not None else int.from_bytes(os.urandom(8), "little", signed=False)
            self.productId = int.from_bytes(str.encode(productId), "little", signed=False)
            self.mfgData = bytearray(struct.pack("<QQLLBBBBL",
                                                 self.rand0,
                                                 self.rand1,
                                                 self.productId,
                                                 self.serialNum,
                                                 self.usrLen,
                                                 self.bspLen,
                                                 self.rsv,
                                                 self.fmt,
                                                 self.SIGNATURE))
        return

    def __str__(self):
        strData = ''.join('{:02X} '.format(x) for x in self.mfgData)
        if self.valid:
            s = f"rand0:{self.rand0:016X} "
            s += f"rand1:{self.rand1:016X} "
            s += f"pid:{self.productId:08X} "
            s += f"sn:{self.serialNum:04X}\n"
            s += f"\t{strData}"
        else:
            s = "Invalid\n"
            s += f"\t{strData}"
        return s


class DfuDeviceTiva():
    # Tiva processors have minimum flash block size of 1K. DFU messages
    # are designed to take block number in 1K chunks even though some
    # processors have much larger flash block sizes. The initial query
    # of the device will indicate the actual flash sector (block) size
    # which is the smallest erase size.
    CMD_BLK_SIZE = 1024

    def __init__(self, dev):
        self.dev = dev

        # Clear any previous state/stauts
        status = dev.getStatus()
        print(status)
        dev.abort()
        status = dev.getStatus()
        print(status)

        info = self.getInfo()
        self.flashBlockSize = info.flashBlockSize
        self.numFlashBlocks = info.numFlashBlocks
        self.cmdBlkMult = self.flashBlockSize // self.CMD_BLK_SIZE
        self.partInfo = info.partInfo
        self.classInfo = info.classInfo
        self.flashTop  = info.flashTop
        self.dfuBlockSize = self.dev.altDesc.wTransferSize
        self.appStartAddr = info.appStartAddr

        # print(f"flashBLockSize:{self.flashBlockSize}\n" +
        #       f"numFlashBlocks:{self.numFlashBlocks}\n" +
        #       f"partInfo:0x{self.partInfo:08X}\n" +
        #       f"clasInfo:{self.classInfo:08X}\n" +
        #       f"flashTop:{self.flashTop:08X}\n" +
        #       f"appStartAddr:0x{self.appStartAddr:08X}")

        self.image = None
        return

    # 0 - numFlashBlocks (Block size depends on part)
    def flashBlockErase(self, blkNum):
        self.dev.tunnelDnloadNoStatus(DfuTivaCmdErase((blkNum * self.cmdBlkMult), 1))
        status = self.dev.getStatus()
        while (status.bState != DfuState.DFU_IDLE):
            time.sleep((status.bwPollTimeout/100))
            status = self.dev.getStatus()

        self.dev.tunnelDnloadNoStatus(DfuTivaCmdCheck((blkNum * self.cmdBlkMult), self.flashBlockSize))
        status = self.dev.getStatus()
        while (status.bStatus != DfuStatus.OK):
            time.sleep((status.bwPollTimeout/100))
            status = self.dev.getStatus()
        return

    # Erase entire Flash
    def flashErase(self, statusCallback=None):
        percentComplete = 0
        for i in range(self.numFlashBlocks):
            self.flashBlockErase(i)
            percentComplete = ((i/self.numFlashBlocks) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)
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

    def flashBlockRead(self, blkNum, statusCallback=None):
        block = bytearray()

        self.uploadPrefixEnable(False)
        self.dev.tunnelDnload(DfuTivaCmdRead((blkNum * self.cmdBlkMult), self.flashBlockSize))
        remain = self.flashBlockSize + 8
        percentComplete = 0
        while remain > 0:
            readSize = self.dfuBlockSize if (remain > self.dfuBlockSize) else remain
            block += bytearray(self.dev.upload(readSize))
            remain -= readSize
            percentComplete = (((self.flashBlockSize - remain)/self.flashBlockSize) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)

        # Remove 8byte header from first packet
        block = block[8:]

        return block

    def flashBlockWrite(self, blkNum, blkData, statusCallback=None):
        # Make sure the passed in data is the right size
        if (len(blkData) != self.flashBlockSize):
            print("ERROR: blkDataLen:{len(blkData)} != flashBlockSize:{self.flashBlockSize}")
            return

        # put the programming command header in front of the raw image
        data = DfuTivaCmdProg((blkNum * self.cmdBlkMult), len(blkData)).packet
        data += blkData
        remain = len(data)
        offset = 0
        ret = 0
        percentComplete = 0
        wBlockNum = 0
        while (remain > 0) and ret is not None:
            writeSize = self.dfuBlockSize if (remain > self.dfuBlockSize) else remain
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

    # Custom function to write to the tail end of flash. Used for manufacturing data
    def mfgWrite(self, mfg):
        mfgBlk = self.flashBlockRead((self.numFlashBlocks-1))
        self.flashBlockErase((self.numFlashBlocks-1))
        mfgBlk = mfgBlk[:-mfg.LEN] + mfg.mfgData
        self.flashBlockWrite((self.numFlashBlocks-1), mfgBlk)
        return

    # Custom function to read out the tail end of flash to pull manufacturing parameters
    def mfgRead(self):
        mfgBlk = self.flashBlockRead((self.numFlashBlocks-1))
        return MfgFmt1(data=mfgBlk[-MfgFmt1.LEN:])

    def imageRead(self, statusCallback=None):
        offset = 0
        size = self.flashTop
        self.image = bytearray()

        self.uploadPrefixEnable(False)
        self.dev.tunnelDnload(DfuTivaCmdRead(offset, size))
        size += 8
        percentComplete = 0
        while size > 0:
            readSize = self.dfuBlockSize if (size > self.dfuBlockSize) else size
            self.image += bytearray(self.dev.upload(readSize))
            percentComplete = (((self.flashTop - size)/self.flashTop) * 100)
            if statusCallback is not None: statusCallback(True, percentComplete)
            size -= readSize

        # Remove 8byte header from first packet
        self.image = self.image[8:]

        return self.image

    # Break up into flash writes into sectors
    # Assume that the flash is erased so skip blocks that are all FFs
    def imageFlash(self, statusCallback=None):
        for i in range(self.numFlashBlocks):
            offset = i * self.flashBlockSize
            data = self.image[offset:(offset+self.flashBlockSize)]
            if ((data[0] != 0xFF) or (len(set(data)) > 1)):
                self.flashBlockWrite(i, data)
            if statusCallback is not None: statusCallback(True, ((i/self.numFlashBlocks) * 100))
        if statusCallback is not None: statusCallback(True, 100)
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
def dfuTivaFindAll(vendorId=0x1CBE, productId=0x00FF):
    devices = dfuFindAll(vendorId, productId)
    devs = []
    for dev in devices:
        ret = dev.send(DfuRequestTivaQuery())
        if (DfuResponseTivaQuery(ret).valid):
            devs.append(dev)
    return devs

def main():
    devs = dfuTivaFindAll()
    tiva = DfuDeviceTiva(devs[0])
    mfg = tiva.mfgRead()
    print(mfg)
    # mfg = MfgFmt1(productId='LPM1', serialNum=0x1234)
    # print(mfg)
    # tiva.mfgWrite(mfg)
    # mfg = tiva.mfgRead()
    # print(mfg)
    return

if __name__ == "__main__":
    main()
    sys.exit(0)