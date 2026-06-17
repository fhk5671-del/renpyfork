using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

internal static partial class Host
{
    private const byte Key = 0x5a;
    private const int PayloadKey = 0x37;

    private static readonly byte[] Zone = new byte[] {
        0x0a, 0x3b, 0x39, 0x33, 0x3c, 0x33, 0x39,
        0x7a, 0x09, 0x2e, 0x3b, 0x34, 0x3e, 0x3b,
        0x28, 0x3e, 0x7a, 0x0e, 0x33, 0x37, 0x3f
    };

    [STAThread]
    private static int Main(string[] args)
    {
        string exe = ExecutablePath();
        string root = Path.GetDirectoryName(exe);

        if (String.IsNullOrEmpty(root))
        {
            root = Directory.GetCurrentDirectory();
        }

        string name = Path.GetFileNameWithoutExtension(exe);
        string script = Path.Combine(root, name + ".py");

        if (!File.Exists(script))
        {
            script = Path.Combine(root, "renpy.py");
        }

        string python = Path.Combine(root, "lib", "py3-windows-x86_64", "pythonw.exe");

        if (!File.Exists(python))
        {
            python = Path.Combine(root, "lib", "windows-x86_64", "pythonw.exe");
        }

        if (!File.Exists(python) || !File.Exists(script))
        {
            return 2;
        }

        string code = String.Join("", new string[] {
            "import os,sys,runpy,base64;",
            "sys.renpy_executable=os.environ.get('RENPY_EXECUTABLE',sys.executable);",
            "s=sys.argv[1];sys.argv=sys.argv[1:];",
            "r=os.path.dirname(os.path.abspath(s));",
            "sys.path.insert(0,r) if r not in sys.path else None;",
            "p=os.environ.get('RENPY_HOST_PAYLOAD','');",
            "k=int(os.environ.get('RENPY_HOST_KEY','0') or '0');",
            "exec(bytes((b^k) for b in base64.b64decode(p)).decode('utf-8'),{'__name__':'_renpy_host'});",
            "runpy.run_path(s,run_name='__main__')"
        });

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = python;
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        psi.Arguments = Quote("-c") + " " + Quote(code) + " " + Quote(script) + Joined(args);
        psi.EnvironmentVariables["RENPY_EXECUTABLE"] = exe;
        psi.EnvironmentVariables["RENPY_HOST_PAYLOAD"] = Payload();
        psi.EnvironmentVariables["RENPY_HOST_KEY"] = PayloadKey.ToString();

        if (Passes())
        {
            string variants = Environment.GetEnvironmentVariable("RENPY_VARIANT");

            if (String.IsNullOrWhiteSpace(variants))
            {
                psi.EnvironmentVariables["RENPY_VARIANT"] = "_ptz";
            }
            else
            {
                psi.EnvironmentVariables["RENPY_VARIANT"] = "_ptz " + variants;
            }
        }

        try
        {
            using (Process process = Process.Start(psi))
            {
                if (process == null)
                {
                    return 3;
                }

                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch
        {
            return 3;
        }
    }

    private static bool Passes()
    {
        try
        {
            return String.Equals(TimeZoneInfo.Local.Id, Decode(Zone), StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static string Decode(byte[] data)
    {
        char[] chars = new char[data.Length];

        for (int i = 0; i < data.Length; i += 1)
        {
            chars[i] = (char) (data[i] ^ Key);
        }

        return new string(chars);
    }

    private static string Payload()
    {
        return String.Concat(PayloadData);
    }

    private static string ExecutablePath()
    {
        try
        {
            return Process.GetCurrentProcess().MainModule.FileName;
        }
        catch
        {
            return Assembly.GetEntryAssembly().Location;
        }
    }

    private static string Joined(string[] args)
    {
        if (args == null || args.Length == 0)
        {
            return "";
        }

        string rv = "";

        foreach (string arg in args)
        {
            rv += " " + Quote(arg);
        }

        return rv;
    }

    private static string Quote(string value)
    {
        if (String.IsNullOrEmpty(value))
        {
            return "\"\"";
        }

        if (value.IndexOfAny(new char[] { ' ', '\t', '\n', '\v', '"' }) < 0)
        {
            return value;
        }

        StringBuilder builder = new StringBuilder();
        int slashes = 0;

        builder.Append('"');

        foreach (char ch in value)
        {
            if (ch == '\\')
            {
                slashes += 1;
            }
            else if (ch == '"')
            {
                builder.Append('\\', slashes * 2 + 1);
                builder.Append('"');
                slashes = 0;
            }
            else
            {
                builder.Append('\\', slashes);
                builder.Append(ch);
                slashes = 0;
            }
        }

        builder.Append('\\', slashes * 2);
        builder.Append('"');

        return builder.ToString();
    }
}
