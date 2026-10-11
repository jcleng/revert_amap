import jadx.api.*;
import java.io.*;
import java.net.*;
import java.util.*;

/**
 * Persistent JADX query server over TCP (localhost).
 * Protocol: one request per line; response framed
 *   <<<BEGIN <id> <CMD>\n ... \n<<<END <id>
 * Commands: MEMBERS | SEARCH <sub> | CLASS <fqcn> | SMALI <fqcn> |
 *           METHODS <fqcn> | FIELDS <fqcn> | WHO <fqcn> |
 *           MMETHOD <sub> | CALLERS <fqcn>#<method> | STR <sub> | QUIT
 */
public class JadxServer {
    static Map<String, JavaClass> byName = new HashMap<>();

    static Object constOf(JavaField f) {
        try {
            jadx.api.plugins.input.data.annotations.EncodedValue ev =
                f.getFieldNode().get(jadx.api.plugins.input.data.attributes.JadxAttrType.CONSTANT_VALUE);
            return ev == null ? null : ev.getValue();
        } catch (Throwable t) {
            return null;
        }
    }

    public static void main(String[] args) throws Exception {
        File apk = new File(args[0]);
        int port = args.length > 1 ? Integer.parseInt(args[1]) : 47811;
        int threads = args.length > 2 ? Integer.parseInt(args[2]) : 4;
        JadxArgs a = new JadxArgs();
        a.setInputFile(apk);
        a.setThreadsCount(threads);
        a.setSkipResources(true);
        a.setShowInconsistentCode(true);
        JadxDecompiler d = new JadxDecompiler(a);
        long t0 = System.currentTimeMillis();
        d.load();
        for (JavaClass c : d.getClassesWithInners()) {
            byName.put(c.getFullName(), c);
            byName.putIfAbsent(c.getRawName(), c);
        }
        System.err.println("LOADED classes=" + byName.size() + " ms=" + (System.currentTimeMillis() - t0));

        ServerSocket ss = new ServerSocket(port, 50, InetAddress.getByName("127.0.0.1"));
        System.err.println("LISTENING " + port);
        final int[] idc = {0};
        while (true) {
            Socket s = ss.accept();
            s.setTcpNoDelay(true);
            new Thread(() -> serve(s, idc), "conn").start();
        }
    }

    static synchronized int nextId(int[] idc) { return ++idc[0]; }

    static void serve(Socket s, int[] idc) {
        try (Socket sock = s;
             BufferedReader in = new BufferedReader(new InputStreamReader(sock.getInputStream(), "UTF-8"));
             PrintStream out = new PrintStream(sock.getOutputStream(), true, "UTF-8")) {
            String line;
            while ((line = in.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                int sp = line.indexOf(' ');
                String cmd = sp < 0 ? line : line.substring(0, sp);
                String arg = sp < 0 ? "" : line.substring(sp + 1).trim();
                int id = nextId(idc);
                out.println("<<<BEGIN " + id + " " + cmd);
                try {
                    handle(cmd, arg, out);
                } catch (Throwable t) {
                    out.println("ERROR " + t);
                }
                out.println("<<<END " + id);
                if (cmd.equals("QUIT")) break;
            }
        } catch (IOException e) {
            // client went away
        }
    }

    static void handle(String cmd, String arg, PrintStream out) {
        switch (cmd) {
            case "PING":
                out.println("PONG");
                break;
            case "MEMBERS":
                out.println("classes=" + byName.size());
                break;
            case "SEARCH": {
                int n = 0;
                for (String k : byName.keySet()) {
                    if (k.contains(arg)) { out.println(k); if (++n > 400) { out.println("...truncated"); break; } }
                }
                break;
            }
            case "CLASS": {
                JavaClass c = byName.get(arg);
                out.println(c == null ? "NOT_FOUND" : c.getCode());
                break;
            }
            case "SMALI": {
                JavaClass c = byName.get(arg);
                out.println(c == null ? "NOT_FOUND" : c.getSmali());
                break;
            }
            case "METHODS": {
                JavaClass c = byName.get(arg);
                if (c == null) { out.println("NOT_FOUND"); break; }
                for (JavaMethod m : c.getMethods()) out.println(m.getFullName() + "  |  " + m.getMethodNode().getMethodInfo().getShortId());
                break;
            }
            case "FIELDS": {
                JavaClass c = byName.get(arg);
                if (c == null) { out.println("NOT_FOUND"); break; }
                for (JavaField f : c.getFields()) out.println(f.getFullName() + " : " + f.getType() + " = " + constOf(f));
                break;
            }
            case "WHO": {
                JavaClass c = byName.get(arg);
                if (c == null) { out.println("NOT_FOUND"); break; }
                for (JavaNode n : c.getUseIn()) out.println(n.getFullName());
                break;
            }
            case "MMETHOD": {
                int n = 0;
                outer:
                for (Map.Entry<String, JavaClass> e : byName.entrySet()) {
                    JavaClass c = e.getValue();
                    if (!c.getFullName().equals(e.getKey())) continue;
                    for (JavaMethod m : c.getMethods()) {
                        if (m.getFullName().contains(arg)) {
                            out.println(m.getFullName());
                            if (++n > 300) { out.println("...truncated"); break outer; }
                        }
                    }
                }
                break;
            }
            case "CALLERS": {
                int h = arg.lastIndexOf('#');
                if (h < 0) { out.println("USAGE: CALLERS Class#method"); break; }
                JavaClass c = byName.get(arg.substring(0, h));
                if (c == null) { out.println("NOT_FOUND"); break; }
                String mn = arg.substring(h + 1);
                int n = 0;
                for (JavaMethod m : c.getMethods()) {
                    if (!m.getName().equals(mn)) continue;
                    for (JavaNode u : m.getUseIn()) { out.println(u.getFullName()); n++; }
                }
                if (n == 0) out.println("NO_CALLERS");
                break;
            }
            case "STR": {
                int n = 0;
                outer:
                for (Map.Entry<String, JavaClass> e : byName.entrySet()) {
                    JavaClass c = e.getValue();
                    if (!c.getFullName().equals(e.getKey())) continue;
                    for (JavaField f : c.getFields()) {
                        Object cv = constOf(f);
                        if (cv instanceof String && ((String) cv).contains(arg)) {
                            out.println(c.getFullName() + "  " + f.getName() + " = " + cv);
                            if (++n > 200) { out.println("...truncated"); break outer; }
                        }
                    }
                }
                if (n == 0) out.println("NONE");
                break;
            }
            default:
                out.println("UNKNOWN_CMD " + cmd);
        }
    }
}
