@echo off
REM Chinese entry: forwards to the main launcher launcher_me.bat.
REM All logic lives in launcher_me.bat for easy maintenance.
REM This file is ASCII-only so cmd parses it correctly under any codepage.
call "%~dp0launcher_me.bat"
