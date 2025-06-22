// src/extension.ts
import * as vscode from "vscode";
import { spawn, SpawnOptionsWithoutStdio, execSync, ChildProcess } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

let dynamicProcess: ChildProcess | null = null;

// --- 인터페이스 정의 ---
interface ExtensionConfig {
  enable: boolean;
  severityLevel: vscode.DiagnosticSeverity;
  enableDynamicAnalysis: boolean;
  ignoredErrorTypes: string[];
  minAnalysisLength: number;
  pythonPath: string | null;
  enableInlayHints: boolean;
}
interface ErrorInfo {
  message: string;
  line: number;
  column: number;
  to_line?: number;
  end_column?: number;
  errorType: string;
}
interface CallGraphData {
  nodes: { id: string; [key: string]: any }[];
  links: { source: string; target: string; [key: string]: any }[];
}
interface AnalysisResult {
  errors: ErrorInfo[];
  call_graph: CallGraphData | null;
}

// --- 전역 변수 ---
let outputChannel: vscode.OutputChannel;
let diagnosticCollection: vscode.DiagnosticCollection;
let lastUsedPythonExecutable: string | null = null;
let checkedPackages = false;
let debounceTimeout: NodeJS.Timeout | null = null;
const inlayHintsCache = new Map<string, vscode.InlayHint[]>();

// --- 확장 기능 활성화 함수 ---
export function activate(context: vscode.ExtensionContext) {
  try {
    outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
    diagnosticCollection =
      vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);

    const debounceDelay = 500;

    function getConfiguration(): ExtensionConfig {
      const config = vscode.workspace.getConfiguration("findRuntimeErr");
      const severityLevel = config.get<string>("severityLevel", "error");
      let diagnosticSeverity: vscode.DiagnosticSeverity;
      switch (severityLevel.toLowerCase()) {
        case "warning":
          diagnosticSeverity = vscode.DiagnosticSeverity.Warning;
          break;
        case "information":
          diagnosticSeverity = vscode.DiagnosticSeverity.Information;
          break;
        case "hint":
          diagnosticSeverity = vscode.DiagnosticSeverity.Hint;
          break;
        case "error":
        default:
          diagnosticSeverity = vscode.DiagnosticSeverity.Error;
          break;
      }
      return {
        enable: config.get<boolean>("enable", true),
        severityLevel: diagnosticSeverity,
        enableDynamicAnalysis: config.get<boolean>(
          "enableDynamicAnalysis",
          false
        ),
        ignoredErrorTypes: config
          .get<string[]>("ignoredErrorTypes", [])
          .map((t) => t.toLowerCase()),
        minAnalysisLength: config.get<number>("minAnalysisLength", 10),
        pythonPath: config.get<string | null>("pythonPath", null),
        enableInlayHints: config.get<boolean>("enableInlayHints", true),
      };
    }

    async function getSelectedPythonPath(
      resource?: vscode.Uri
    ): Promise<string> {
      const config = getConfiguration();
      if (config.pythonPath) return config.pythonPath;
      try {
        const pythonExtension =
          vscode.extensions.getExtension("ms-python.python");
        if (pythonExtension) {
          if (!pythonExtension.isActive) {
            await pythonExtension.activate();
          }
          const api = pythonExtension.exports;
          const envPath =
            api?.environments?.getActiveEnvironmentPath(resource)?.path;
          if (envPath) {
            const environment = await api.environments.resolveEnvironment(
              envPath
            );
            if (environment?.path) return environment.path;
          }
        }
      } catch (err) {
        /* Fallback */
      }
      const defaultPath = vscode.workspace
        .getConfiguration("python", resource)
        .get<string>("defaultInterpreterPath");
      if (defaultPath) return defaultPath;
      for (const cmd of ["python3", "python"]) {
        try {
          execSync(`${cmd} --version`, { stdio: "ignore" });
          return cmd;
        } catch {
          /* Fallback */
        }
      }
      throw new Error("Could not find a valid Python interpreter.");
    }

    function checkPythonPackages(pythonExecutable: string): {
      missing: string[];
    } {
      const requiredPackages = ["parso", "astroid", "networkx"];
      const missingPackages = requiredPackages.filter((pkg) => {
        try {
          execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
            stdio: "pipe",
          });
          return false;
        } catch {
          return true;
        }
      });
      return { missing: missingPackages };
    }

    async function runAnalysisProcess(
      code: string,
      mode: "realtime" | "static",
      documentUri?: vscode.Uri
    ): Promise<AnalysisResult> {
      let pythonExecutable: string;
      try {
        pythonExecutable = await getSelectedPythonPath(documentUri);
      } catch (e: any) {
        return {
          errors: [
            {
              message: `Python path error: ${e.message}`,
              line: 1,
              column: 0,
              errorType: "PythonPathError",
            },
          ],
          call_graph: null,
        };
      }
      if (lastUsedPythonExecutable !== pythonExecutable) {
        lastUsedPythonExecutable = pythonExecutable;
        checkedPackages = false;
      }
      return new Promise((resolve) => {
        try {
          if (!checkedPackages) {
            const checkResult = checkPythonPackages(pythonExecutable);
            if (checkResult.missing.length > 0) {
              resolve({
                errors: [
                  {
                    message: `Missing packages: ${checkResult.missing.join(
                      ", "
                    )}. Please install them.`,
                    line: 1,
                    column: 0,
                    errorType: "MissingDependencyError",
                  },
                ],
                call_graph: null,
              });
              return;
            }
            checkedPackages = true;
          }
          const scriptPath = path.join(
            context.extensionPath,
            "scripts",
            "main.py"
          );
          const baseDir = documentUri
            ? path.dirname(documentUri.fsPath)
            : context.extensionPath;
          const args = [scriptPath, mode, baseDir];
          const spawnOptions: SpawnOptionsWithoutStdio = {
            cwd: path.dirname(scriptPath),
          };
          const pythonProcess = spawn(pythonExecutable, args, spawnOptions);

          let stdoutData = "";
          let stderrData = "";
          pythonProcess.stdin.write(code, "utf-8");
          pythonProcess.stdin.end();
          pythonProcess.stdout.on("data", (data) => {
            stdoutData += data.toString("utf-8");
          });
          pythonProcess.stderr.on("data", (data) => {
            stderrData += data.toString("utf-8");
          });
          pythonProcess.on("close", (closeCode) => {
            if (closeCode !== 0 && !stdoutData.trim()) {
              resolve({
                errors: [
                  {
                    message: `Analysis failed (Code: ${closeCode}). Stderr: ${stderrData.trim()}`,
                    line: 1,
                    column: 0,
                    errorType: "AnalysisScriptError",
                  },
                ],
                call_graph: null,
              });
              return;
            }
            try {
              const result: AnalysisResult = JSON.parse(stdoutData.trim());
              if (result && Array.isArray(result.errors)) {
                resolve(result);
              } else {
                throw new Error("Invalid analysis result format.");
              }
            } catch (e: any) {
              resolve({
                errors: [
                  {
                    message: `Error parsing analysis result: ${e.message}`,
                    line: 1,
                    column: 0,
                    errorType: "JSONParseError",
                  },
                ],
                call_graph: null,
              });
            }
          });
          pythonProcess.on("error", (err) => {
            resolve({
              errors: [
                {
                  message: `Failed to start analysis: ${err.message}`,
                  line: 1,
                  column: 0,
                  errorType: "SpawnError",
                },
              ],
              call_graph: null,
            });
          });
        } catch (e: any) {
          resolve({
            errors: [
              {
                message: `Error setting up analysis: ${e.message}`,
                line: 1,
                column: 0,
                errorType: "SetupError",
              },
            ],
            call_graph: null,
          });
        }
      });
    }

    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult
    ) {
      if (!result || !Array.isArray(result.errors)) return;
      const filteredErrors = result.errors.filter(
        (err) => !config.ignoredErrorTypes.includes(err.errorType.toLowerCase())
      );
      const inlayHints = createInlayHints(filteredErrors, config);
      inlayHintsCache.set(documentUri.toString(), inlayHints);
      displayDiagnostics(documentUri, config, filteredErrors);
    }

    const createRange = (err: ErrorInfo): vscode.Range => {
      const line = Math.max(0, err.line - 1);
      const column = Math.max(0, err.column);
      const toLine = Math.max(line, (err.to_line ?? err.line) - 1);
      const endColumn = Math.max(column + 1, err.end_column ?? column + 1);
      return new vscode.Range(line, column, toLine, endColumn);
    };

    function createInlayHints(
      errors: ErrorInfo[],
      config: ExtensionConfig
    ): vscode.InlayHint[] {
      const hints: vscode.InlayHint[] = [];
      if (!config.enableInlayHints) return hints;
      for (const err of errors) {
        const { severity } = getSeverity(err.errorType);
        if (severity <= config.severityLevel) {
          let hintText: string | undefined;
          if (err.errorType === "W0701")
            hintText = `// Potential infinite loop`;
          else if (err.errorType === "W0801")
            hintText = `// Potential recursion`;

          if (hintText) {
            const range = createRange(err);
            const position = new vscode.Position(
              range.start.line,
              range.end.character
            );
            const hint = new vscode.InlayHint(position, hintText);
            hint.paddingLeft = true;
            hints.push(hint);
          }
        }
      }
      return hints;
    }

    function getSeverity(errorType: string): {
      severity: vscode.DiagnosticSeverity;
    } {
      if (errorType.toUpperCase().startsWith("E"))
        return { severity: vscode.DiagnosticSeverity.Error };
      if (errorType.toUpperCase().startsWith("W"))
        return { severity: vscode.DiagnosticSeverity.Warning };
      return { severity: vscode.DiagnosticSeverity.Information };
    }

    function displayDiagnostics(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      errors: ErrorInfo[]
    ) {
      const diagnostics: vscode.Diagnostic[] = [];
      errors.forEach((err) => {
        const { severity } = getSeverity(err.errorType);
        if (severity <= config.severityLevel) {
          const range = createRange(err);
          const diagnostic = new vscode.Diagnostic(
            range,
            err.message,
            severity
          );
          diagnostic.source = "FindRuntimeErr";
          diagnostic.code = err.errorType;
          diagnostics.push(diagnostic);
        }
      });
      diagnosticCollection.set(documentUri, diagnostics);
    }

    function clearPreviousAnalysis(documentUri: vscode.Uri) {
      diagnosticCollection.delete(documentUri);
      inlayHintsCache.delete(documentUri.toString());
    }

    const hoverProvider = vscode.languages.registerHoverProvider(
      { language: "python" },
      {
        provideHover(document, position) {
          const diagnosticsAtPos = diagnosticCollection
            .get(document.uri)
            ?.filter((d) => d.range.contains(position));
          if (!diagnosticsAtPos?.length) return undefined;
          const hoverContent = new vscode.MarkdownString(
            diagnosticsAtPos
              .map((d) => `**[${d.code}]** ${d.message}`)
              .join("\n\n---\n\n")
          );
          return new vscode.Hover(hoverContent, diagnosticsAtPos[0].range);
        },
      }
    );
    context.subscriptions.push(hoverProvider);

    const inlayHintsProvider = vscode.languages.registerInlayHintsProvider(
      { language: "python" },
      {
        provideInlayHints: (doc) =>
          inlayHintsCache.get(doc.uri.toString()) || [],
      }
    );
    context.subscriptions.push(inlayHintsProvider);

    const triggerRealtimeAnalysis = (document: vscode.TextDocument) => {
      if (document.languageId !== "python" || document.uri.scheme !== "file")
        return;
      if (debounceTimeout) clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        const config = getConfiguration();
        if (
          !config.enable ||
          document.getText().length < config.minAnalysisLength
        ) {
          clearPreviousAnalysis(document.uri);
          return;
        }
        clearPreviousAnalysis(document.uri);
        runAnalysisProcess(document.getText(), "realtime", document.uri)
          .then((result) => handleAnalysisResult(document.uri, config, result))
          .catch(() => {}); // Errors are handled inside runAnalysisProcess
      }, debounceDelay);
    };

    context.subscriptions.push(
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (vscode.window.activeTextEditor?.document === event.document)
          triggerRealtimeAnalysis(event.document);
      })
    );
    context.subscriptions.push(
      vscode.workspace.onDidOpenTextDocument((doc) => {
        if (doc.languageId === "python") triggerRealtimeAnalysis(doc);
      })
    );
    context.subscriptions.push(
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor?.document.languageId === "python")
          triggerRealtimeAnalysis(editor.document);
      })
    );
    context.subscriptions.push(
      vscode.workspace.onDidCloseTextDocument((doc) =>
        clearPreviousAnalysis(doc.uri)
      )
    );
    context.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (
          e.affectsConfiguration("findRuntimeErr") ||
          e.affectsConfiguration("python.defaultInterpreterPath")
        ) {
          checkedPackages = false;
          if (vscode.window.activeTextEditor)
            triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
        }
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.analyzeCurrentFile",
        async () => {
          const editor = vscode.window.activeTextEditor;
          if (editor?.document.languageId === "python") {
            clearPreviousAnalysis(editor.document.uri);
            const config = getConfiguration();
            await vscode.window.withProgress(
              {
                location: vscode.ProgressLocation.Notification,
                title: "FindRuntimeErr: 정적 분석 중...",
              },
              async () => {
                const result = await runAnalysisProcess(
                  editor.document.getText(),
                  "static",
                  editor.document.uri
                );
                handleAnalysisResult(editor.document.uri, config, result);
                vscode.window.showInformationMessage(
                  `정적 분석 완료. ${result.errors.length}개 이슈 발견.`
                );
              }
            );
          }
        }
      )
    );
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.runDynamicAnalysis",

        () => {
          const editor = vscode.window.activeTextEditor;
          if (editor && editor.document.languageId === "python") {
            outputChannel.appendLine("[Command] findRuntimeErr.runDynamicAnalysis executed.");
            const config = getConfiguration();
            clearPreviousAnalysis(editor.document.uri);

            runDynamicAnalysisProcess(editor.document.getText(), editor.document.uri)
              .then((result) => {
                handleAnalysisResult(editor.document.uri, config, result, "dynamic");
                // Function-level error summary
                const summaryCounts: { [fn: string]: number } = {};
                result.errors.forEach(err => {
                  const match = err.message.match(/Function `(.+?)` failed/);
                  const fn = match ? match[1] : 'unknown';
                  summaryCounts[fn] = (summaryCounts[fn] || 0) + 1;
                });
                outputChannel.appendLine('[Dynamic Analysis Summary]');
                for (const [fn, cnt] of Object.entries(summaryCounts)) {
                  outputChannel.appendLine(`  ${fn}: ${cnt} error(s)`);
                }
                vscode.window.showInformationMessage(
                  `FindRuntimeErr: Dynamic analysis completed. ${result.errors.length} error(s) found.`
                );
              })
              .catch((error) => {
                outputChannel.appendLine(`[Command Error] Dynamic analysis failed: ${error.message}`);
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: Dynamic analysis failed. ${error.message}`
                );
              });
          } else {
            vscode.window.showWarningMessage(
              "FindRuntimeErr: Please open a Python file to run dynamic analysis."
            );
          }
        })
    );
    // Command to kill the running dynamic analysis Python process
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.killPythonProcess",
        () => {
          if (dynamicProcess) {
            dynamicProcess.kill();
            outputChannel.appendLine("[Command] Python process killed by user.");
            vscode.window.showInformationMessage(
              "FindRuntimeErr: Python process has been terminated."
            );
            dynamicProcess = null;
          } else {
            vscode.window.showWarningMessage(
              "FindRuntimeErr: No Python process is currently running."
            );
          }
        }
      )
    );

    if (vscode.window.activeTextEditor)
      triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
  } catch (e: any) {
    vscode.window.showErrorMessage(
      `FindRuntimeErr failed to activate: ${e.message}.`
    );
  }
}

export function deactivate() {
  if (debounceTimeout) clearTimeout(debounceTimeout);
}
