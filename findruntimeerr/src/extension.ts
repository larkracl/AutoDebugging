// src/extension.ts
import * as vscode from "vscode";
import { spawn, SpawnOptionsWithoutStdio, execSync } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// --- 인터페이스 정의 ---
interface ExtensionConfig {
  enable: boolean;
  severityLevel: vscode.DiagnosticSeverity;
  enableDynamicAnalysis: boolean;
  ignoredErrorTypes: string[];
  minAnalysisLength: number;
  pythonPath: string | null;
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
  nodes: { id: string; type?: string; lineno?: number }[];
  links: {
    source: string;
    target: string;
    type?: string;
    call_sites?: number[];
  }[];
  [key: string]: any;
}
interface AnalysisResult {
  errors: ErrorInfo[];
  call_graph: CallGraphData | null;
}

let outputChannel: vscode.OutputChannel;
let diagnosticCollection: vscode.DiagnosticCollection;
let errorDecorationType: vscode.TextEditorDecorationType;

export function activate(context: vscode.ExtensionContext) {
  try {
    outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
    outputChannel.appendLine(
      "FindRuntimeErr 확장 프로그램이 활성화되었습니다."
    );

    diagnosticCollection =
      vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);

    errorDecorationType = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy green",
    });

    let debounceTimeout: NodeJS.Timeout | null = null;
    const debounceDelay = 500;
    let checkedPackages = false;
    let lastUsedPythonExecutable: string | null = null;

    // --- getConfiguration 함수 ---
    function getConfiguration(): ExtensionConfig {
      try {
        const config = vscode.workspace.getConfiguration("findRuntimeErr");
        const severityLevel = config.get<string>("severityLevel", "error");
        let diagnosticSeverity: vscode.DiagnosticSeverity;
        switch (severityLevel) {
          case "warning":
            diagnosticSeverity = vscode.DiagnosticSeverity.Warning;
            break;
          case "information":
            diagnosticSeverity = vscode.DiagnosticSeverity.Information;
            break;
          case "hint":
            diagnosticSeverity = vscode.DiagnosticSeverity.Hint;
            break;
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
          ignoredErrorTypes: config.get<string[]>("ignoredErrorTypes", []),
          minAnalysisLength: config.get<number>("minAnalysisLength", 50),
          pythonPath: config.get<string | null>("pythonPath", null),
        };
      } catch (e: any) {
        console.error("Error getting configuration:", e);
        outputChannel.appendLine(
          `ERROR getting configuration: ${e.message}\n${e.stack}`
        );
        return {
          enable: true,
          severityLevel: vscode.DiagnosticSeverity.Error,
          enableDynamicAnalysis: false,
          ignoredErrorTypes: [],
          minAnalysisLength: 50,
          pythonPath: null,
        };
      }
    }

    // --- getPythonExecutablePath 함수 ---
    async function getPythonExecutablePath(
      context: vscode.ExtensionContext,
      config: ExtensionConfig
    ): Promise<string> {
      try {
        if (config.pythonPath && fs.existsSync(config.pythonPath)) {
          outputChannel.appendLine(
            `[getPythonPath] Using pythonPath from settings: ${config.pythonPath}`
          );
          return config.pythonPath;
        }
        const isDevContainer =
          !!process.env.VSCODE_REMOTE_CONTAINERS_SESSION ||
          !!process.env.CODESPACES ||
          context.extensionMode === vscode.ExtensionMode.Development;
        if (isDevContainer) {
          outputChannel.appendLine(
            "[getPythonPath] Detected Dev Container environment."
          );
          const containerPythons = [
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            "/bin/python3",
            "/usr/bin/python",
          ];
          for (const pyPath of containerPythons) {
            try {
              execSync(`${pyPath} --version`);
              outputChannel.appendLine(
                `[getPythonPath] Using Dev Container Python: ${pyPath}`
              );
              return pyPath;
            } catch (error) {
              outputChannel.appendLine(
                `[getPythonPath] Path ${pyPath} not found or not executable.`
              );
            }
          }
          outputChannel.appendLine(
            "[getPythonPath] Could not find a valid system Python in Dev Container, falling back to 'python3'."
          );
          return "python3";
        } else {
          outputChannel.appendLine(
            "[getPythonPath] Local environment detected. Trying VSCode Python extension API."
          );
          try {
            const pythonExtension =
              vscode.extensions.getExtension("ms-python.python");
            if (pythonExtension) {
              if (!pythonExtension.isActive) {
                await pythonExtension.activate();
              }
              if (pythonExtension.exports && pythonExtension.exports.settings) {
                const resourceUri =
                  vscode.window.activeTextEditor?.document.uri ||
                  vscode.workspace.workspaceFolders?.[0]?.uri;
                const executionDetails =
                  pythonExtension.exports.settings.getExecutionDetails(
                    resourceUri
                  );
                if (executionDetails?.execCommand?.[0]) {
                  const vscodePythonPath = executionDetails.execCommand[0];
                  try {
                    execSync(`${vscodePythonPath} --version`);
                    outputChannel.appendLine(
                      `[getPythonPath] Using Python path from VSCode Python extension: ${vscodePythonPath}`
                    );
                    return vscodePythonPath;
                  } catch (error) {
                    outputChannel.appendLine(
                      `[getPythonPath] Path from VSCode Python extension is invalid: ${vscodePythonPath}. Error: ${error}`
                    );
                  }
                } else {
                  outputChannel.appendLine(
                    `[getPythonPath] Could not get execution details from VSCode Python extension.`
                  );
                }
              } else {
                outputChannel.appendLine(
                  `[getPythonPath] VSCode Python extension exports or settings not available.`
                );
              }
            } else {
              outputChannel.appendLine(
                `[getPythonPath] VSCode Python extension not found.`
              );
            }
          } catch (err: any) {
            outputChannel.appendLine(
              `[getPythonPath] Error accessing VSCode Python extension API: ${err.message}`
            );
          }
          outputChannel.appendLine(
            "[getPythonPath] Falling back to 'python3' command."
          );
          return "python3";
        }
      } catch (e: any) {
        console.error("Error determining Python executable path:", e);
        outputChannel.appendLine(
          `ERROR determining Python executable path: ${e.message}\n${e.stack}`
        );
        return "python3";
      }
    }

    // --- checkPythonPackages 함수 ---
    function checkPythonPackages(
      pythonExecutable: string,
      packages: string[]
    ): { missing: string[]; error?: string } {
      const missingPackages: string[] = [];
      let checkError: string | undefined;
      outputChannel.appendLine(
        `[checkPackages] Checking for packages using interpreter: ${pythonExecutable}`
      );
      for (const pkg of packages) {
        try {
          const command = `${pythonExecutable} -m pip show ${pkg}`;
          outputChannel.appendLine(`[checkPackages] Running: ${command}`);
          execSync(command);
          outputChannel.appendLine(`[checkPackages] Package found: ${pkg}`);
        } catch (error: any) {
          outputChannel.appendLine(
            `[checkPackages] Package not found: ${pkg}. Error status: ${error.status}`
          );
          if (error.stderr) {
            outputChannel.appendLine(
              `[checkPackages] Stderr: ${error.stderr.toString()}`
            );
          }
          if (error.stdout) {
            outputChannel.appendLine(
              `[checkPackages] Stdout: ${error.stdout.toString()}`
            );
          }
          missingPackages.push(pkg);
          const errorMsg = error.stderr?.toString() || error.message || "";
          if (
            errorMsg.includes("No such file or directory") ||
            errorMsg.includes("command not found")
          ) {
            checkError = `Failed to run Python ('${pythonExecutable}'). Is it installed and in PATH?`;
            outputChannel.appendLine(
              `[checkPackages] Python executable check failed: ${checkError}`
            );
            break;
          }
        }
      }
      return { missing: missingPackages, error: checkError };
    }

    // --- runAnalysisProcess 함수 ---
    async function runAnalysisProcess(
      code: string,
      mode: "realtime" | "static"
    ): Promise<AnalysisResult> {
      const config = getConfiguration();
      let pythonExecutable: string;
      try {
        pythonExecutable = await getPythonExecutablePath(context, config);
      } catch (e: any) {
        outputChannel.appendLine(
          `[runAnalysis] Failed to get Python executable path: ${e.message}`
        );
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

      lastUsedPythonExecutable = pythonExecutable;

      return new Promise((resolve) => {
        try {
          let proceedAnalysis = true;
          // 패키지 확인 (매번 실행)
          const requiredPackages = ["astroid", "networkx"];
          const checkResult = checkPythonPackages(
            pythonExecutable,
            requiredPackages
          );
          if (checkResult.error) {
            resolve({
              errors: [
                {
                  message: checkResult.error,
                  line: 1,
                  column: 0,
                  errorType: "PythonPathError",
                },
              ],
              call_graph: null,
            });
            return;
          }
          if (checkResult.missing.length > 0) {
            const missing = checkResult.missing.join(", ");
            const message = `FindRuntimeErr requires: ${missing}. Please run 'pip install ${missing}' in your Python environment ('${pythonExecutable}'). Analysis skipped.`;
            resolve({
              errors: [
                {
                  message: message,
                  line: 1,
                  column: 0,
                  errorType: "MissingDependencyError",
                },
              ],
              call_graph: null,
            });
            proceedAnalysis = false;
            // checkedPackages = true; // 이 플래그를 다시 사용하려면 activate 스코프 유지 필요
          }
          // checkedPackages = true; // 성공 시 다시 체크 안 함

          if (!proceedAnalysis) {
            return;
          }

          const extensionRootPath = context.extensionPath;
          const scriptDir = path.join(extensionRootPath, "scripts");
          const mainScriptPath = path.join(scriptDir, "main.py");

          if (!fs.existsSync(mainScriptPath)) {
            throw new Error(
              `main.py script not found at path: ${mainScriptPath}`
            );
          }

          const spawnOptions: SpawnOptionsWithoutStdio = { cwd: scriptDir };
          outputChannel.appendLine(
            `[runAnalysis] Spawning: ${pythonExecutable} ${mainScriptPath} ${mode} in ${scriptDir}`
          );
          const pythonProcess = spawn(
            pythonExecutable,
            [mainScriptPath, mode],
            spawnOptions
          );
          let stdoutData = "";
          let stderrData = "";

          pythonProcess.stdin.write(code);
          pythonProcess.stdin.end();
          pythonProcess.stdout.on("data", (data) => {
            stdoutData += data;
          });
          pythonProcess.stderr.on("data", (data) => {
            stderrData += data;
            outputChannel.appendLine(`[Py Stderr] ${data}`);
          });

          pythonProcess.on("close", (closeCode) => {
            try {
              outputChannel.appendLine(
                `[runAnalysis] Python process finished with code: ${closeCode} (${mode})`
              );
              if (closeCode !== 0) {
                let errorDetail = `Analysis script failed (Exit Code: ${closeCode}).`;
                let errorType = "AnalysisScriptError";
                let errorLine = 1;
                let errorColumn = 0;
                if (stdoutData.trim()) {
                  try {
                    const errorResult = JSON.parse(stdoutData);
                    if (errorResult?.errors?.[0]) {
                      errorDetail =
                        errorResult.errors[0].message || errorDetail;
                      errorType = errorResult.errors[0].errorType || errorType;
                      errorLine = errorResult.errors[0].line || errorLine;
                      errorColumn = errorResult.errors[0].column || errorColumn;
                    }
                  } catch {}
                }
                if (
                  stderrData.trim() &&
                  !errorDetail.includes(stderrData.trim())
                ) {
                  errorDetail += `\nStderr: ${stderrData.trim()}`;
                }
                resolve({
                  errors: [
                    {
                      message: errorDetail,
                      line: errorLine,
                      column: errorColumn,
                      errorType: errorType,
                    },
                  ],
                  call_graph: null,
                });
                return;
              }
              outputChannel.appendLine(
                `[runAnalysis] Raw stdout (${mode}): ${stdoutData}`
              );
              if (!stdoutData.trim()) {
                resolve({ errors: [], call_graph: null });
                return;
              }
              const result: AnalysisResult = JSON.parse(stdoutData);
              if (result && Array.isArray(result.errors)) {
                resolve(result);
              } else {
                resolve({
                  errors: [
                    {
                      message:
                        "Invalid analysis result format. 'errors' key missing/not array.",
                      line: 1,
                      column: 0,
                      errorType: "InvalidFormatError",
                    },
                  ],
                  call_graph: null,
                });
              }
            } catch (parseError: any) {
              resolve({
                errors: [
                  {
                    message: `Error parsing analysis results: ${
                      parseError.message
                    }. Raw: ${stdoutData.substring(0, 100)}...`,
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
          console.error("Error setting up or spawning Python process:", e);
          outputChannel.appendLine(
            `ERROR setting up or spawning Python: ${e.message}\n${e.stack}`
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

    function runDynamicAnalysisProcess(code: string): Promise<AnalysisResult> {
      return new Promise((resolve, reject) => {
        const pythonExecutable = path.join(
          context.extensionPath,
          "venv",
          "bin",
          "python"
        );
        const scriptPath = path.join(context.extensionPath, "scripts", "dynamic_analyze.py");
        outputChannel.appendLine(`[runDynamicAnalysis] Spawning: ${pythonExecutable} ${scriptPath}`);
        const pythonProcess = spawn(pythonExecutable, [scriptPath]);
  
        let stdoutData = "";
        let stderrData = "";
  
        pythonProcess.stdin.write(code);
        pythonProcess.stdin.end();
  
        pythonProcess.stdout.on("data", (data) => {
          stdoutData += data;
        });
        pythonProcess.stderr.on("data", (data) => {
          stderrData += data;
          outputChannel.appendLine(`[Dynamic Py Stderr] ${data}`);
        });
  
        pythonProcess.on("close", (closeCode) => {
          outputChannel.appendLine(`[runDynamicAnalysis] Python process exited with code: ${closeCode}`);
          if (closeCode !== 0) {
            reject(new Error(`Dynamic analysis failed. Stderr: ${stderrData.trim()}`));
            return;
          }
          try {
            const result: AnalysisResult = JSON.parse(stdoutData);
            resolve(result);
          } catch (error: any) {
            reject(new Error(`Error parsing dynamic analysis result: ${error.message}`));
          }
        });
  
        pythonProcess.on("error", (err) => {
          reject(new Error(`Failed to start dynamic analysis: ${err.message}`));
        });
      });
    }

    // --- 분석 로직 (analyzeCode) ---
    async function analyzeCode(
      code: string,
      documentUri: vscode.Uri,
      mode: "realtime" | "static" = "realtime",
      showProgress: boolean = false
    ) {
      try {
        const config = getConfiguration();

        if (mode === "realtime") {
          if (!config.enable) {
            outputChannel.appendLine(
              "[analyzeCode] Real-time analysis disabled."
            );
            clearPreviousAnalysis(documentUri);
            return;
          }
          if (code.length < config.minAnalysisLength) {
            outputChannel.appendLine(
              `[analyzeCode] Code length (${code.length}) < minAnalysisLength (${config.minAnalysisLength}). Skipping real-time analysis.`
            );
            clearPreviousAnalysis(documentUri);
            return;
          }
        }

        clearPreviousAnalysis(documentUri);

        let analysisResult: AnalysisResult | null = null;

        if (showProgress) {
          await vscode.window.withProgress(
            {
              location: vscode.ProgressLocation.Notification,
              title: "FindRuntimeErr: 분석 실행 중...",
              cancellable: false,
            },
            async (progress) => {
              try {
                progress.report({ message: "정적 분석 수행 중..." });
                analysisResult = await runAnalysisProcess(code, mode);
                handleAnalysisResult(documentUri, config, analysisResult, mode);
                const scriptErrors = analysisResult.errors.filter((e) =>
                  [
                    "AnalysisScriptError",
                    "JSONParseError",
                    "InvalidFormatError",
                    "SpawnError",
                    "AnalysisTimeoutError",
                    "UnexpectedError",
                    "InternalImportError",
                    "CheckerLoadError",
                    "CoreAnalysisError",
                    "SetupError",
                    "AnalysisErrorRT",
                    "MissingDependencyError",
                    "ProcessExecutionError",
                    "PythonPathError",
                  ].includes(e.errorType)
                );
                if (scriptErrors.length > 0) {
                  vscode.window.showWarningMessage(
                    `FindRuntimeErr: 분석 중 문제 발생 (${scriptErrors[0].errorType}). Problems 패널 확인.`
                  );
                } else {
                  vscode.window.showInformationMessage(
                    `FindRuntimeErr: 분석 완료. ${analysisResult.errors.length}개의 잠재적 오류 발견.`
                  );
                }
                outputChannel.appendLine(
                  `[analyzeCode] Analysis processed (${mode}). ${analysisResult.errors.length} potential issues found.`
                );
              } catch (error: any) {
                console.error(
                  "Unexpected error during analysis progress:",
                  error
                );
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: 예상치 못한 분석 오류 발생. ${error.message}`
                );
                outputChannel.appendLine(
                  `[analyzeCode] Unexpected analysis error during progress (${mode}): ${error.message}`
                );
                handleAnalysisResult(
                  documentUri,
                  config,
                  {
                    errors: [
                      {
                        message: `Unexpected analysis error: ${error.message}`,
                        line: 1,
                        column: 0,
                        errorType: "UnexpectedError",
                      },
                    ],
                    call_graph: null,
                  },
                  mode
                );
              }
            }
          );
        } else {
          // 실시간 분석
          try {
            analysisResult = await runAnalysisProcess(code, mode);
            handleAnalysisResult(documentUri, config, analysisResult, mode);
          } catch (error: any) {
            console.error("Real-time analysis failed unexpectedly:", error);
            outputChannel.appendLine(
              `[analyzeCode] Real-time analysis failed unexpectedly: ${error.message}`
            );
            handleAnalysisResult(
              documentUri,
              config,
              {
                errors: [
                  {
                    message: `Analysis failed: ${error.message}`,
                    line: 1,
                    column: 0,
                    errorType: "AnalysisErrorRT",
                  },
                ],
                call_graph: null,
              },
              mode
            );
          }
        }
        if (!analysisResult) {
          outputChannel.appendLine(
            `[analyzeCode] Analysis finished with null result (${mode}).`
          );
          clearPreviousAnalysis(documentUri);
        }
      } catch (e: any) {
        console.error("Error in analyzeCode:", e);
        outputChannel.appendLine(
          `ERROR in analyzeCode: ${e.message}\n${e.stack}`
        );
      }
    }

    // --- 결과 처리 및 표시 함수 (handleAnalysisResult) ---
    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult,
      mode: string
    ) {
      try {
        // result.errors가 배열인지 다시 한번 확인 (매우 중요)
        if (!(result && Array.isArray(result.errors))) {
          const errorMsg = `Invalid 'errors' format received: ${JSON.stringify(
            result
          )}`;
          outputChannel.appendLine(`[handleResult] ${errorMsg}`);
          // Problems 패널에 내부 오류 표시
          displayDiagnostics(documentUri, config, [
            {
              message: errorMsg,
              line: 1,
              column: 0,
              errorType: "InvalidResultFormatError",
            },
          ]);
          return; // 더 이상 진행하지 않음
        }

        const errors: ErrorInfo[] = result.errors;
        outputChannel.appendLine(
          `[handleResult] Processing ${errors.length} diagnostics/errors.`
        );
        displayDiagnostics(documentUri, config, errors); // 진단 정보 표시

        const callGraphData = result.call_graph;
        const hasScriptError = errors.some((e) =>
          [
            "AnalysisScriptError",
            "JSONParseError",
            "InvalidFormatError",
            "SpawnError",
            "AnalysisTimeoutError",
            "UnexpectedError",
            "InternalImportError",
            "CheckerLoadError",
            "CoreAnalysisError",
            "SetupError",
            "AnalysisErrorRT",
            "MissingDependencyError",
            "ProcessExecutionError",
            "PythonPathError",
            "HandleResultError",
            "InvalidResultFormatError",
          ].includes(e.errorType)
        );

        if (callGraphData && mode === "static" && !hasScriptError) {
          outputChannel.appendLine(`[handleResult] Call graph data received:`);
          outputChannel.appendLine(JSON.stringify(callGraphData, null, 2)); // Output 채널에 JSON 출력
          console.log("Call Graph Data:", callGraphData); // 디버그 콘솔에도 출력
        }
      } catch (error: any) {
        console.error("Error handling analysis result:", error);
        outputChannel.appendLine(
          `ERROR handling analysis result: ${error.message}\n${error.stack}`
        );
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(0, 0, 0, 0),
          `Internal Error handling results: ${error.message}`,
          vscode.DiagnosticSeverity.Error
        );
        diagnostic.source = "FindRuntimeErr";
        diagnosticCollection.set(documentUri, [diagnostic]);
      }
    }

    // --- 진단 정보 표시 함수 (displayDiagnostics) ---
    function displayDiagnostics(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      errors: ErrorInfo[]
    ) {
      if (!Array.isArray(errors)) {
        outputChannel.appendLine(
          `[displayDiagnostics] CRITICAL ERROR: Invalid errors object received (not an array): ${JSON.stringify(
            errors
          )}`
        );
        diagnosticCollection.set(documentUri, []);
        const editor = vscode.window.activeTextEditor;
        if (
          editor &&
          editor.document.uri.toString() === documentUri.toString()
        ) {
          editor.setDecorations(errorDecorationType, []);
        }
        return;
      }
      try {
        outputChannel.appendLine(
          `[displayDiagnostics] Displaying ${errors.length} diagnostics.`
        );
        const diagnostics: vscode.Diagnostic[] = [];
        const decorationRanges: vscode.Range[] = [];

        errors.forEach((error) => {
          try {
            if (
              !error ||
              typeof error.message !== "string" ||
              typeof error.line !== "number" ||
              typeof error.column !== "number" ||
              typeof error.errorType !== "string"
            ) {
              /* ... 스킵 ... */ return;
            }
            const isInternalError = [
              "AnalysisScriptError",
              "JSONParseError",
              "InvalidFormatError",
              "SpawnError",
              "AnalysisTimeoutError",
              "UnexpectedError",
              "InternalImportError",
              "CheckerLoadError",
              "CoreAnalysisError",
              "SetupError",
              "AnalysisErrorRT",
              "MissingDependencyError",
              "ProcessExecutionError",
              "PythonPathError",
              "HandleResultError",
              "InvalidResultFormatError",
            ].includes(error.errorType); // 내부 오류 타입 추가
            const severity = isInternalError
              ? vscode.DiagnosticSeverity.Error
              : config.severityLevel;
            const finalSeverity =
              error.errorType === "SyntaxError"
                ? vscode.DiagnosticSeverity.Error
                : severity;
            if (
              !isInternalError &&
              config.ignoredErrorTypes.includes(error.errorType)
            ) {
              return;
            }

            const line = Math.max(0, error.line - 1);
            const column = Math.max(0, error.column);
            // 끝 위치 정보 사용 (없으면 기본값)
            const toLine = Math.max(line, (error.to_line ?? error.line) - 1);
            const endColumn = Math.max(
              column + 1,
              error.end_column ?? column + 1
            );
            const range = isInternalError
              ? new vscode.Range(0, 0, 0, 1)
              : new vscode.Range(line, column, toLine, endColumn); // 수정된 Range

            const message = isInternalError
              ? `FindRuntimeErr Internal Error: ${error.message}`
              : `${error.message} : ${error.errorType} : Line ${error.line}, Column ${error.column} : "AutoDebugging"`;
            const diagnostic = new vscode.Diagnostic(
              range,
              message,
              finalSeverity
            );
            diagnostic.source = "FindRuntimeErr";
            diagnostic.code = error.errorType;
            diagnostics.push(diagnostic);

            if (
              !isInternalError &&
              (finalSeverity === vscode.DiagnosticSeverity.Error ||
                finalSeverity === vscode.DiagnosticSeverity.Warning)
            ) {
              decorationRanges.push(range);
            }
          } catch (e: any) {
            outputChannel.appendLine(
              `[displayDiagnostics] Error processing individual error object: ${e.message}\n${e.stack}`
            );
          }
        });

        diagnosticCollection.set(documentUri, diagnostics); // Problems 패널 업데이트

        const editor = vscode.window.activeTextEditor;
        if (
          editor &&
          editor.document.uri.toString() === documentUri.toString()
        ) {
          outputChannel.appendLine(
            `[displayDiagnostics] Setting decorations for ${decorationRanges.length} ranges.`
          );
          editor.setDecorations(errorDecorationType, decorationRanges); // 밑줄 업데이트
        }
      } catch (e: any) {
        console.error("Error displaying diagnostics:", e);
        outputChannel.appendLine(
          `ERROR displaying diagnostics: ${e.message}\n${e.stack}`
        );
      }
    }
    // --- 이전 분석 결과 지우는 함수 ---
    function clearPreviousAnalysis(documentUri: vscode.Uri) {
      try {
        /* ... 이전과 동일 ... */
      } catch (e: any) {
        /* ... */
      }
    }

    // --- Hover Provider ---
    const hoverProvider = vscode.languages.registerHoverProvider("python", {
      provideHover(document, position, token) {
        try {
          const diagnostics = diagnosticCollection.get(document.uri);
          if (!diagnostics) {
            return undefined;
          }
          for (const diagnostic of diagnostics) {
            if (diagnostic.range.contains(position)) {
              const hoverContent = new vscode.MarkdownString();
              hoverContent.isTrusted = true;
              hoverContent.supportHtml = true;
              hoverContent.appendMarkdown(
                `**[FindRuntimeErr] ${diagnostic.code || "Error"}**\n\n`
              );
              hoverContent.appendMarkdown(
                `${diagnostic.message.split(" : ")[0].trim()}\n\n`
              );
              // 추가 정보 (예시)
              // if (diagnostic.code === 'NameError') { hoverContent.appendMarkdown(`*Hint: Check definition.*`); }
              if (
                diagnostic.source === "FindRuntimeErr" &&
                diagnostic.message.startsWith("FindRuntimeErr Internal Error:")
              ) {
                hoverContent.appendMarkdown(
                  `\n\n---\n\n**Internal Info:**\n${diagnostic.message}`
                );
              }
              return new vscode.Hover(hoverContent, diagnostic.range);
            }
          }
          return undefined;
        } catch (e: any) {
          console.error("Error in HoverProvider:", e);
          outputChannel.appendLine(
            `ERROR in HoverProvider: ${e.message}\n${e.stack}`
          );
          return undefined;
        }
      },
    });
    context.subscriptions.push(hoverProvider);

    // --- 이벤트 리스너 및 명령어 등록 (try...catch 포함) ---
    vscode.workspace.onDidChangeTextDocument((event) => {
      try {
        /* ... */
      } catch (e: any) {
        /* ... */
      }
    });
    vscode.workspace.onDidOpenTextDocument((document) => {
      try {
        /* ... */
      } catch (e: any) {
        /* ... */
      }
    });
    vscode.workspace.onDidChangeConfiguration((e) => {
      try {
        /* ... */ checkedPackages = false; /* ... */
      } catch (e: any) {
        /* ... */
      }
    });
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.analyzeCurrentFile",
        () => {
          try {
            /* ... */
          } catch (e: any) {
            /* ... */
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

        runDynamicAnalysisProcess(editor.document.getText())
          .then((result) => {
            handleAnalysisResult(editor.document.uri, config, result, "dynamic");
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

    // --- 초기 실행 ---
    if (
      vscode.window.activeTextEditor &&
      vscode.window.activeTextEditor.document.languageId === "python"
    ) {
      try {
        /* ... */
      } catch (e: any) {
        /* ... */
      }
    }
  } catch (e: any) {
    // activate 함수 자체 오류 처리
    console.error("Error during extension activation:", e);
    vscode.window.showErrorMessage(
      `FindRuntimeErr failed to activate: ${e.message}`
    );
  }
} // activate 함수 끝

export function deactivate() {
  try {
    if (outputChannel) {
      outputChannel.dispose();
    }
    console.log("FindRuntimeErr extension deactivated.");
  } catch (e: any) {
    console.error("Error during extension deactivation:", e);
  }
}
