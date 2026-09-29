import static com.verygood.security.larky.ModuleSupplier.CORE_MODULES;
import com.verygood.security.larky.ModuleSupplier;
import com.verygood.security.larky.console.LogConsole;
import com.verygood.security.larky.parser.LarkyScript;
import com.verygood.security.larky.parser.PathBasedStarFile;
import java.nio.file.Paths;

public class RunStar {
  public static void main(String[] args) throws Exception {
    var console = LogConsole.writeOnlyConsole(System.out, false);
    var moduleSet = new ModuleSupplier().modulesToVariableMap(true);
    var interpreter = new LarkyScript(CORE_MODULES, LarkyScript.StarlarkMode.STRICT);
    int failed = 0;
    for (String f : args) {
      try {
        interpreter.evaluate(new PathBasedStarFile(Paths.get(f).toAbsolutePath(), null, null), moduleSet, console);
        System.out.println("OK " + f);
      } catch (Exception e) {
        failed++;
        System.out.println("FAIL " + f + ": " + e.getMessage());
      }
    }
    System.exit(failed == 0 ? 0 : 1);
  }
}
