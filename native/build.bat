@echo off
REM Build gdeflate.dll - GDeflate (Apache-2.0, NVIDIA/Microsoft) decompressor
REM wrapped for use from Python via ctypes.
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 (echo vcvars failed & exit /b 1)

cd /d "%~dp0"
if not exist out mkdir out
if not exist obj mkdir obj

cl /nologo /O2 /MD /EHsc /DNDEBUG /D_CRT_SECURE_NO_WARNINGS ^
   /I "libdeflate" /I "gdeflate" ^
   /Fo:obj\ /Fd:obj\vc.pdb ^
   /LD wrapper.cpp gdeflate\GDeflateDecompress.cpp ^
   libdeflate\lib\adler32.c libdeflate\lib\crc32.c ^
   libdeflate\lib\deflate_decompress.c libdeflate\lib\gdeflate_decompress.c ^
   libdeflate\lib\utils.c libdeflate\lib\x86\cpu_features.c ^
   /link /OUT:out\gdeflate.dll /IMPLIB:out\gdeflate.lib /INCREMENTAL:NO
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo BUILD OK
dir /b out