using System.Diagnostics;

namespace ToolEditDeleteCmt;

public static class UpdateInstaller
{
    public static void ScheduleInstall(string downloadedExePath)
    {
        if (string.IsNullOrWhiteSpace(downloadedExePath) || !File.Exists(downloadedExePath))
        {
            throw new FileNotFoundException("Không tìm thấy file cập nhật đã tải.", downloadedExePath);
        }

        var currentExePath = Application.ExecutablePath;
        var currentProcessId = Environment.ProcessId;
        var scriptPath = Path.Combine(Path.GetTempPath(), "FlowMetaUpdate", "install-update.cmd");
        Directory.CreateDirectory(Path.GetDirectoryName(scriptPath)!);

        var script = $"""
@echo off
setlocal
set "SRC={downloadedExePath}"
set "DST={currentExePath}"
set "NEW={currentExePath}.new"
set "BAK={currentExePath}.bak"
set "PID={currentProcessId}"

:wait
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)

if not exist "%SRC%" exit /b 1
copy /Y "%SRC%" "%NEW%" >nul
if errorlevel 1 exit /b 1

if exist "%BAK%" del /F /Q "%BAK%" >nul 2>nul
move /Y "%DST%" "%BAK%" >nul
if errorlevel 1 (
  del "%NEW%" >nul 2>nul
  exit /b 1
)

move /Y "%NEW%" "%DST%" >nul
if errorlevel 1 (
  move /Y "%BAK%" "%DST%" >nul 2>nul
  del "%NEW%" >nul 2>nul
  exit /b 1
)

start "" "%DST%"
if errorlevel 1 (
  if exist "%BAK%" move /Y "%BAK%" "%DST%" >nul 2>nul
  exit /b 1
)

del "%SRC%" >nul 2>nul
del "%~f0" >nul 2>nul
""";

        File.WriteAllText(scriptPath, script);
        Process.Start(new ProcessStartInfo
        {
            FileName = scriptPath,
            UseShellExecute = true,
            WindowStyle = ProcessWindowStyle.Hidden
        });
    }
}
