#!/usr/bin/env python
#-------------------------------------------------------------------------------
# Texas Instruments Tiva Device Firmware Update tool
#
# Brian Costabile (bcostabi@gmail.com)
# https://github.com/briancostabile/tiva-dfu.git
# This code is in the public domain
#-------------------------------------------------------------------------------
import os
import sys
import argparse
import datetime
from dfuTiva import DfuDeviceTiva, dfuTivaFindAll

def statusCallback(statusOk, percentComplete):
    print(f"{percentComplete:3.2f}%", end='\r', flush=True)
    return

def fmtPortNumbers(portNumbers):
    return str(portNumbers).strip('(').rstrip(')').rstrip(',').replace(', ', '.')

def printDev(dev):
    d = dev.usbDev
    c = dev.usbCfg
    i = dev.usbIntf
    print("Found TivaDFU: "
            f"[{d.idVendor:04X}:{d.idProduct:04X}] "
            f"ver={d.bcdDevice:04} "
            f"devnum={d.address} "
            f"cfg={c.bConfigurationValue} "
            f"intf={i.bInterfaceNumber} "
            f"path=\"{d.bus}-{fmtPortNumbers(d.port_numbers)}\" "
            f"alt={i.bAlternateSetting} "
            f"name=\"{dev.altName}\" "
            f"serial=\"{d.serial_number}\"")
    return


def programLoop(args):
    devs = dfuTivaFindAll()

    # Quick Error Check
    if devs is None or len(devs) <= 0:
        return False

    # Handle list only if upload and download are not specified:
    if (args.list and ((args.upload is None) and (args.download is None))):
        for dev in devs:
            printDev(dev)
        return True

    # Select the device based on input flags
    # --------- Filter vendor:product
    if args.device is not None:
        pairs = args.device[0].split(",")
        f = []
        for pair in pairs:
            vendor, product = pair.split(":")
            vendor = int(vendor, base=16)
            product = int(product, base=16)
            for dev in devs:
                if (vendor == dev.usbDev.idVendor) and (product == dev.usbDev.idProduct):
                    f.append(dev)
        devs = f

    # --------- Filter devnum
    if args.devnum is not None:
        f = []
        for dev in devs:
            if args.devnum[0] == dev.usbDev.address:
                f.append(dev)
        devs = f

    # --------- Filter Bus/Port
    if args.path is not None:
        bus, port = args.path[0].split("-")
        f = []
        for dev in devs:
            if bus == str(dev.usbDev.bus) and port == fmtPortNumbers(dev.usbDev.port_numbers):
                f.append(dev)
        devs = f

    # --------- Filter Configuration Number
    if args.cfg is not None:
        f = []
        for dev in devs:
            if args.cfg[0] == dev.usbCfg.bConfigurationValue:
                f.append(dev)
        devs = f

    # --------- Filter Interface Number
    if args.intf is not None:
        f = []
        for dev in devs:
            if args.intf[0] == dev.usbIntf.bInterfaceNumber:
                f.append(dev)
        devs = f

    # --------- Filter Serial Number
    if args.serial is not None:
        f = []
        for dev in devs:
            if args.serial[0] == dev.usbDev.serial_number:
                f.append(dev)
        devs = f

    # --------- Filter Alt Number
    if args.alt is not None:
        f = []
        for dev in devs:
            if args.alt[0] == str(dev.usbIntf.bAlternateSetting):
                f.append(dev)
        devs = f

    # Nothing to do if Device is not found
    if devs is None or len(devs) <= 0:
        return False

    # Choose first of the filtered list
    dev = devs[0]
    tiva = DfuDeviceTiva(dev)

    # For download operation, Make sure specified download file exists
    dlFile = None
    if (args.download is not None):
        dlFile = os.path.abspath(args.download[0])
        if not os.path.exists(dlFile):
            print(f"ERROR: {dlFile} does not exist")
            return True

    ulFile = None
    if (args.upload is not None):
        ulFile = os.path.abspath(args.upload[0])

    # Upload takes precedence
    if ulFile:
        tiva.imageRead()
        tiva.dumpBinary(ulFile)

    if dlFile:
        if not tiva.loadElf(dlFile):
            tiva.loadBinary(dlFile)
        print("Reading Manufacturing Area")
        mfg = tiva.mfgRead()
        print("Flash Erasing")
        tiva.flashErase(statusCallback)
        print("\nDone!")
        print("Flash Programming")
        tiva.imageFlash(statusCallback)
        if mfg.valid:
            print("Restoring Manufacturing Area")
            tiva.mfgWrite(mfg)
        print("\nDone!")

    # If reset option passefd in
    if args.reset:
        tiva.reset()

    return True


# So the help only prints the metavar once and no commas between options
class CustomHelpFormatter(argparse.HelpFormatter):
    def _format_action_invocation(self, action):
        if not action.option_strings or action.nargs == 0:
            if action.option_strings:
                return ' '.join(action.option_strings)
            return super()._format_action_invocation(action)
        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return ' '.join(action.option_strings) + ' ' + args_string

# Main program
def main():
    fmt = lambda prog: CustomHelpFormatter(prog)
    parser = argparse.ArgumentParser(
        formatter_class=fmt,
        prog='tiva-dfu-util.py',
        description="TI Tiva Processor Device Firmware Update Utility"
    )

    parser.add_argument(
        "-V", "--version",
        action='version',
        version='%(prog)s 1.0',
        help="Print the version number",
    )

    parser.add_argument(
        "-v", "--verbose",
        action='store_true',
        dest='verbose',
        help="Print verbose debug statements",
    )

    parser.add_argument(
        "-l", "--list",
        action='store_true',
        dest="list",
        help="List currently attached DFU capable devices",
    )

    parser.add_argument(
        "-e", "--detach",
        action='store_true',
        dest="detach",
        help="Detach currently attached DFU capable devices",
    )

    parser.add_argument(
        "-E", "--detach-delay",
        nargs=1,
        type=int,
        default=None,
        action='store',
        dest="detach-delay",
        metavar='<seconds>',
        help="Time to wait before reopening a device after detach",
    )

    parser.add_argument(
        "-d", "--device",
        nargs=1,
        type=str,
        action='store',
        dest="device",
        metavar='<vendor>:<product>[,<vendor_dfu>:<product_dfu>]',
        help="Specify Vendor/Product ID(s) of DFU device",
    )

    parser.add_argument(
        "-n", "--devnum",
        nargs=1,
        type=int,
        default=None,
        action='store',
        dest="devnum",
        metavar='<dnum>',
        help="Match given device number (devnum from --list)",
    )

    parser.add_argument(
        "-p", "--path",
        nargs=1,
        type=str,
        action='store',
        dest="path",
        metavar='<bus-port. ... .port>',
        help="Specify path to DFU device",
    )

    parser.add_argument(
        "-c", "--cfg",
        nargs=1,
        type=int,
        default=None,
        action='store',
        dest="cfg",
        metavar='<config_nr>',
        help="Specify the Configuration of DFU device",
    )

    parser.add_argument(
        "-i", "--intf",
        nargs=1,
        type=int,
        default=None,
        action='store',
        dest="intf",
        metavar='<intf_nr>',
        help="Specify the DFU Interface number",
    )

    parser.add_argument(
        "-S", "--serial",
        nargs=1,
        type=str,
        action='store',
        dest="serial",
        metavar='<serial_string>[,<serial_string_dfu>]',
        help="Specify Serial String of DFU device",
    )

    parser.add_argument(
        "-a", "--alt",
        nargs=1,
        type=str,
        action='store',
        dest="alt",
        metavar='<alt>',
        help="Specify the Altsetting of the DFU Interface by name or by number",
    )

    parser.add_argument(
        "-t", "--transfer-size",
        nargs=1,
        type=int,
        default=None,
        action='store',
        dest="transfer-size",
        metavar='<size>',
        help="Specify the number of bytes per USB Transfer",
    )

    parser.add_argument(
        "-U", "--upload",
        nargs=1,
        type=str,
        action='store',
        dest="upload",
        metavar='<file>',
        help="Read firmware from device into <file>",
    )

    parser.add_argument(
        "-Z", "--upload-size",
        nargs=1,
        type=int,
        default=0,
        action='store',
        dest="upload-size",
        metavar='<bytes>',
        help="Specify the expected upload size in bytes",
    )

    parser.add_argument(
        "-D", "--download",
        nargs=1,
        type=str,
        action='store',
        dest="download",
        metavar='<file>',
        help="Write firmware from <file> into device",
    )

    parser.add_argument(
        "-R", "--reset",
        action='store_true',
        dest="reset",
        help="Issue USB Reset signalling once we're finished",
    )

    parser.add_argument(
        "-w", "--wait",
        action='store_true',
        dest="wait",
        help="Wait for device to appear",
    )

    args = parser.parse_args()

    if args.wait:
        deviceFound = False
        while not deviceFound:
            try:
                deviceFound = programLoop(args)
            except KeyboardInterrupt:
                print(
                    "\n[{}]: Keyboard interrupt detected while waiting for DFU Device".format(
                        datetime.datetime.now()
                    )
                )
                break
    else:
        if not programLoop(args):
            print("ERROR: Device Not Found")

    return

if __name__ == "__main__":
    main()
    sys.exit(0)
