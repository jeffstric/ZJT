// ZhiJuTong native launcher (packaging-free)
//
// A tiny native .NET executable that simply launches launcher_me.bat,
// which in turn runs scripts\launchers\launcher.py via uv.
//
// Unlike the old PyInstaller-built exe, this has NO PyInstaller bootloader
// and NO self-extraction, so antivirus software does not flag it as malware.
//
// Build with the .NET Framework C# compiler (csc.exe ships with Windows):
//   csc /target:winexe /out:点我启动.exe /win32icon:files\logo.ico \
//       /reference:System.dll scripts\build\launcher_exe.cs
//
// See scripts\build\build_launcher_exe.bat for a one-click build.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

internal static class Launcher
{
    // P/Invoke MessageBox so we do not need a System.Windows.Forms reference.
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static int Main()
    {
        try
        {
            // Resolve the directory this exe lives in, then look for launcher_me.bat there.
            string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".";
            string bat = Path.Combine(dir, "launcher_me.bat");

            if (!File.Exists(bat))
            {
                MessageBox(IntPtr.Zero,
                    "Failed to start launcher_me.bat. Please make sure the package is fully extracted.",
                    "ZhiJuTong Launcher", 0x10); // MB_ICONERROR
                return 1;
            }

            // Launch launcher_me.bat. The console stays visible so the first-run
            // dependency install progress (and any errors) can be seen; launcher.py
            // hides the console once the tray is ready. For a fully windowless launch,
            // set WindowStyle = ProcessWindowStyle.Hidden (first-run progress is then hidden).
            Process.Start(new ProcessStartInfo
            {
                FileName = bat,
                WorkingDirectory = dir,
                UseShellExecute = true,
                WindowStyle = ProcessWindowStyle.Normal
            });
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox(IntPtr.Zero, "Startup failed: " + ex.Message, "ZhiJuTong Launcher", 0x10);
            return 1;
        }
    }
}
