// src/extension.ts
import * as vscode from "vscode";
import { spawn, SpawnOptionsWithoutStdio, execSync } from "child_process";
import * as path from "path";
import * as fs from "fs";

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
interface CallGraphNode {
  id: string;
  type?: string;
  lineno?: number;
  [key: string]: any;
}
interface CallGraphLink {
  source: string;
  target: string;
  type?: string;
  call_sites?: number[];
  [key: string]: any;
}
interface CallGraphData {
  nodes: CallGraphNode[];
  links: CallGraphLink[];
  directed?: boolean;
  multigraph?: boolean;
  graph?: any;
  [key: string]: any;
}
interface AnalysisResult {
  errors: ErrorInfo[];
  call_graph: CallGraphData | null;
}

// --- 전역 변수 ---
let outputChannel: vscode.OutputChannel;
let diagnosticCollection: vscode.DiagnosticCollection;
let errorDecorationType: vscode.TextEditorDecorationType;
let lastCallGraph: CallGraphData | null = null;
let checkedPackages = false;
let lastUsedPythonExecutable: string | null = null;
let debounceTimeout: NodeJS.Timeout | null = null;
const inlayHintsCache = new Map<string, vscode.InlayHint[]>();

// --- 확장 기능 활성화 함수 ---
export function activate(context: vscode.ExtensionContext) {
  try {
    outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
    outputChannel.appendLine("Activating FindRuntimeErr extension.");
    diagnosticCollection =
      vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);

    errorDecorationType = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy green",
    });
    context.subscriptions.push(errorDecorationType);

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
          .map((type) => type.toLowerCase()),
        minAnalysisLength: config.get<number>("minAnalysisLength", 10),
        pythonPath: config.get<string | null>("pythonPath", null),
        enableInlayHints: config.get<boolean>("enableInlayHints", true),
      };
    }

    async function getSelectedPythonPath(
      resource?: vscode.Uri
    ): Promise<string> {
      const config = getConfiguration();
      outputChannel.appendLine(
        "[getSelectedPythonPath] Determining Python executable path..."
      );
      if (config.pythonPath) {
        try {
          const stats = await fs.promises.stat(config.pythonPath);
          if (stats.isFile() || stats.isSymbolicLink()) {
            outputChannel.appendLine(
              `[getSelectedPythonPath] Using pythonPath from settings: ${config.pythonPath}`
            );
            return config.pythonPath;
          }
        } catch (e: any) {
          // Ignore error and try next method
        }
      }
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
            if (environment?.path) {
              outputChannel.appendLine(
                `[getSelectedPythonPath] Using Python path from Python extension API (environments): ${environment.path}`
              );
              return environment.path;
            }
          }
        }
      } catch (err: any) {
        // Ignore error and try next method
      }
      const defaultPath = vscode.workspace
        .getConfiguration("python", resource)
        .get<string>("defaultInterpreterPath");
      if (defaultPath) {
        outputChannel.appendLine(
          `[getSelectedPythonPath] Using python.defaultInterpreterPath: ${defaultPath}`
        );
        return defaultPath;
      }
      for (const cmd of ["python3", "python"]) {
        try {
          execSync(`${cmd} --version`, { stdio: "ignore" });
          outputChannel.appendLine(
            `[getSelectedPythonPath] Using '${cmd}' found in PATH.`
          );
          return cmd;
        } catch {
          /* next */
        }
      }
      throw new Error("Could not find a valid Python interpreter.");
    }

    function checkPythonPackages(pythonExecutable: string): {
      missing: string[];
      error?: string;
    } {
      const requiredPackages = ["parso", "astroid", "networkx"];
      const missingPackages: string[] = [];
      for (const pkg of requiredPackages) {
        try {
          execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
            stdio: "pipe",
          });
        } catch (error) {
          missingPackages.push(pkg);
        }
      }
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
        return Promise.resolve({
          errors: [
            {
              message: `Failed to determine Python path: ${e.message}`,
              line: 1,
              column: 0,
              errorType: "PythonPathError",
            },
          ],
          call_graph: null,
        });
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
              const errorMsg = `FindRuntimeErr requires: ${checkResult.missing.join(
                ", "
              )}. Please install them.`;
              resolve({
                errors: [
                  {
                    message: errorMsg,
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
          if (!fs.existsSync(scriptPath))
            throw new Error(`Analysis script not found: ${scriptPath}`);

          // --- 여기가 핵심 수정 ---
          const baseDir = documentUri
            ? path.dirname(documentUri.fsPath)
            : context.extensionPath;
          const args = [scriptPath, mode, baseDir];

          const spawnOptions: SpawnOptionsWithoutStdio = {
            cwd: path.dirname(scriptPath),
          };
          outputChannel.appendLine(
            `[runAnalysisProcess] Spawning: "${pythonExecutable}" "${args.join(
              '" "'
            )}"`
          );

          const pythonProcess = spawn(pythonExecutable, args, spawnOptions);

          let stdoutData = "";
          let stderrData = "";
          pythonProcess.stdin.write(code, "utf-8");
          pythonProcess.stdin.end();

          pythonProcess.stdout.on("data", (data) => {
            stdoutData += data.toString("utf-8");
          });
          pythonProcess.stderr.on("data", (data) => {
            const chunk = data.toString("utf-8");
            stderrData += chunk;
            chunk.split("\n").forEach((line: string) => {
              if (line.trim()) outputChannel.appendLine(`[Py Stderr] ${line}`);
            });
          });

          pythonProcess.on("close", (closeCode) => {
            outputChannel.appendLine(
              `[runAnalysisProcess] Python process exited with code: ${closeCode}`
            );
            if (stderrData.trim())
              outputChannel.appendLine(
                `[runAnalysisProcess] Full Stderr from Python:\n${stderrData}`
              );

            const trimmedStdout = stdoutData.trim();
            outputChannel.appendLine(
              `[runAnalysisProcess] Raw stdout before JSON.parse (Mode: ${mode}):\n${trimmedStdout}`
            );

            if (closeCode !== 0 && !trimmedStdout) {
              resolve({
                errors: [
                  {
                    message: `Analysis script failed (Code: ${closeCode}). Stderr: ${stderrData.trim()}`,
                    line: 1,
                    column: 0,
                    errorType: "AnalysisScriptError",
                  },
                ],
                call_graph: null,
              });
              return;
            }
            if (!trimmedStdout) {
              resolve({ errors: [], call_graph: null });
              return;
            }

            try {
              const result: AnalysisResult = JSON.parse(trimmedStdout);
              outputChannel.appendLine(
                `[runAnalysisProcess] Parsed result.errors.length: ${
                  result?.errors?.length ?? "undefined"
                }`
              );
              if (result && Array.isArray(result.errors)) {
                resolve(result);
              } else {
                throw new Error("Invalid analysis result format.");
              }
            } catch (parseError: any) {
              outputChannel.appendLine(
                `[runAnalysisProcess] Error parsing analysis results: ${parseError.message}.`
              );
              resolve({
                errors: [
                  {
                    message: `Error parsing analysis results: ${parseError.message}`,
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
            outputChannel.appendLine(
              `[runAnalysisProcess] Python process error: ${err.message}`
            );
            resolve({
              errors: [
                {
                  message: `Failed to start analysis process: ${err.message}`,
                  line: 1,
                  column: 0,
                  errorType: "SpawnError",
                },
              ],
              call_graph: null,
            });
          });
        } catch (e: any) {
          outputChannel.appendLine(
            `ERROR in runAnalysisProcess setup: ${e.message}\n${e.stack}`
          );
          resolve({
            errors: [
              {
                message: `Error setting up analysis process: ${e.message}`,
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

    async function runDynamicAnalysisProcess(
      code: string,
      documentUri?: vscode.Uri
    ): Promise<AnalysisResult> {
      // 이 함수는 현재 토픽과 무관하므로 기존 로직을 그대로 사용한다고 가정
      return Promise.resolve({ errors: [], call_graph: null });
    }

    async function analyzeCodeRealtime(
      document: vscode.TextEditor["document"]
    ) {
      try {
        const code = document.getText();
        const config = getConfiguration();
        if (!config.enable || code.length < config.minAnalysisLength) {
          clearPreviousAnalysis(document.uri);
          return;
        }
        clearPreviousAnalysis(document.uri);
        const analysisResult = await runAnalysisProcess(
          code,
          "realtime",
          document.uri
        );
        lastCallGraph = analysisResult.call_graph;
        handleAnalysisResult(document.uri, config, analysisResult, "realtime");
      } catch (e: any) {
        outputChannel.appendLine(
          `ERROR in analyzeCodeRealtime: ${e.message}\n${e.stack}`
        );
      }
    }

    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult,
      mode: "realtime" | "static" | "dynamic"
    ) {
      if (!result || !Array.isArray(result.errors)) return;

      outputChannel.appendLine(
        `[handleAnalysisResult] Received ${result.errors.length} errors (before filtering) for ${documentUri.fsPath} (Mode: ${mode}):`
      );
      result.errors.forEach((err, index) => {
        outputChannel.appendLine(
          `  [RawErr ${index + 1}] Type: ${err.errorType}, Line: ${
            err.line
          }, Msg: ${err.message.substring(0, 70)}...`
        );
      });

      const filteredErrors = result.errors.filter(
        (err) => !config.ignoredErrorTypes.includes(err.errorType.toLowerCase())
      );
      outputChannel.appendLine(
        `[handleAnalysisResult] ${filteredErrors.length} errors after 'ignoredErrorTypes' filtering.`
      );

      const inlayHints = createInlayHints(filteredErrors, config);
      inlayHintsCache.set(documentUri.toString(), inlayHints);

      displayDiagnostics(documentUri, config, filteredErrors);

      if (mode === "static" && result.call_graph) {
        outputChannel.appendLine(
          `[handleAnalysisResult] Call graph: ${result.call_graph.nodes.length} nodes, ${result.call_graph.links.length} links.`
        );
      }
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
        const { severity } = getSeverityAndUnderline(err.errorType, config);
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

    function getSeverityAndUnderline(
      errorType: string,
      config: ExtensionConfig
    ): { severity: vscode.DiagnosticSeverity; underline: boolean } {
      const lowerType = errorType.toLowerCase();
      let severity: vscode.DiagnosticSeverity;
      if (lowerType.startsWith("e")) severity = vscode.DiagnosticSeverity.Error;
      else if (lowerType.startsWith("w"))
        severity = vscode.DiagnosticSeverity.Warning;
      else severity = vscode.DiagnosticSeverity.Information;
      return { severity, underline: true };
    }

    function displayDiagnostics(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      errors: ErrorInfo[]
    ) {
      const diagnostics: vscode.Diagnostic[] = [];
      errors.forEach((err) => {
        const { severity } = getSeverityAndUnderline(err.errorType, config);
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
          if (!diagnosticsAtPos || diagnosticsAtPos.length === 0)
            return undefined;
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
        provideInlayHints(
          document: vscode.TextDocument
        ): vscode.ProviderResult<vscode.InlayHint[]> {
          return inlayHintsCache.get(document.uri.toString()) || [];
        },
      }
    );
    context.subscriptions.push(inlayHintsProvider);

    const triggerRealtimeAnalysis = (document: vscode.TextDocument) => {
      if (document.languageId !== "python" || document.uri.scheme !== "file")
        return;
      if (debounceTimeout) clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        analyzeCodeRealtime(document).catch(() => {});
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
                lastCallGraph = result.call_graph;
                handleAnalysisResult(
                  editor.document.uri,
                  config,
                  result,
                  "static"
                );
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
        async () => {
          /* ... */
        }
      )
    );

    if (vscode.window.activeTextEditor)
      triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
  } catch (e: any) {
    console.error("FATAL Error during extension activation:", e);
    vscode.window.showErrorMessage(
      `FindRuntimeErr failed to activate: ${e.message}.`
    );
  }
}

export function deactivate() {
  outputChannel?.dispose();
  if (debounceTimeout) clearTimeout(debounceTimeout);
}
