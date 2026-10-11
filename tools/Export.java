import jadx.api.*;
import java.io.File;

public class Export {
    public static void main(String[] args) throws Exception {
        JadxArgs a = new JadxArgs();
        a.setInputFile(new File(args[0]));
        a.setOutDir(new File(args[1]));
        a.setThreadsCount(4);
        a.setSkipResources(true);
        JadxDecompiler d = new JadxDecompiler(a);
        d.load();
        System.err.println("loaded classes=" + d.getClasses().size());
        d.saveSources();
        System.err.println("SAVED to " + args[1]);
        d.close();
    }
}
