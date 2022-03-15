# tiva-dfu
Python DFU library for Texas Instruments Tiva platforms

Can be used standalone or imported into larger Python project. Depends on pyelftools for converting elf file into binary file.

Main script for command line testing is tiva-dfu-util.py. That's modeled after the dfu-util command line tool found here: http://dfu-util.sourceforge.net/

Two subttle differences with other DFU flasher programs:
* This one does not include any prefix header or suffix trailer on the binary data downloaded or uploaded.
* This program accepts ELF/DWARF formatted files for downloading. It depends on pyelftools to flatten the program into a binary.

## License
This software is licensed under the MIT License. It's free to use by anyone
