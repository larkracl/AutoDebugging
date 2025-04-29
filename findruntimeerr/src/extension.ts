// src/extension.ts
import * as vscode from "vscode";
import { spawn, SpawnOptionsWithoutStdio } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

const outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");

// --- 인터페이스 정의 ---
interface ExtensionConfig {
  enable: boolean;
  severityLevel: vscode.DiagnosticSeverity;
  enableDynamicAnalysis: boolean;
  ignoredErrorTypes: string[];
  minAnalysisLength: number;
}

interface ErrorInfo {
  message: string;
  line: number;
  column: number;
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

export function activate(context: vscode.ExtensionContext) {
  try {
    // --- activate 함수 전체 try...catch ---
    outputChannel.appendLine(
      "FindRuntimeErr 확장 프로그램이 활성화되었습니다."
    );

    const diagnosticCollection =
      vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);

    const errorDecorationType = vscode.window.createTextEditorDecorationType({
      textDecoration: "underline wavy green",
    });

    let debounceTimeout: NodeJS.Timeout | null = null;
    const debounceDelay = 500;

    function getConfiguration(): ExtensionConfig {
      try {
        // getConfiguration 내부 try...catch (선택적)
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
        };
      } catch (e: any) {
        console.error("Error getting configuration:", e);
        outputChannel.appendLine(
          `ERROR getting configuration: ${e.message}\n${e.stack}`
        );
        // 기본값 반환 또는 에러 throw
        return {
          // 기본값 반환 예시
          enable: true,
          severityLevel: vscode.DiagnosticSeverity.Error,
          enableDynamicAnalysis: false,
          ignoredErrorTypes: [],
          minAnalysisLength: 50,
        };
      }
    }

    // 분석 실행 함수 (Promise 반환)
    function runAnalysisProcess(
      code: string,
      mode: "realtime" | "static"
    ): Promise<AnalysisResult> {
      return new Promise((resolve, reject) => {
        try {
          // runAnalysisProcess 내부 try...catch (spawn 전)
          const extensionRootPath = context.extensionPath;
          const scriptDir = path.join(extensionRootPath, "scripts");
          const mainScriptPath = path.join(scriptDir, "main.py");
          let pythonExecutable =
            process.platform === "win32"
              ? path.join(extensionRootPath, ".venv", "Scripts", "python.exe")
              : path.join(extensionRootPath, ".venv", "bin", "python");

          if (!fs.existsSync(pythonExecutable)) {
            const python3Executable =
              process.platform === "win32"
                ? path.join(
                    extensionRootPath,
                    ".venv",
                    "Scripts",
                    "python3.exe"
                  )
                : path.join(extensionRootPath, ".venv", "bin", "python3");
            if (fs.existsSync(python3Executable)) {
              pythonExecutable = python3Executable;
            } else {
              throw new Error(
                `Python interpreter not found in .venv: Checked ${pythonExecutable} and ${python3Executable}`
              );
            } // 에러 throw
          }
          if (!fs.existsSync(mainScriptPath)) {
            throw new Error(
              `main.py script not found at path: ${mainScriptPath}`
            );
          } // 에러 throw

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
              // close 핸들러 내부 try...catch
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
              // 성공 시
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
                        "Invalid analysis result format. 'errors' key is missing or not an array.",
                      line: 1,
                      column: 0,
                      errorType: "InvalidFormatError",
                    },
                  ],
                  call_graph: null,
                });
              } // reject 대신 오류 정보 resolve
            } catch (parseError: any) {
              resolve({
                errors: [
                  {
                    message: `Error parsing analysis results: ${
                      parseError.message
                    }. Raw data: ${stdoutData.substring(0, 100)}...`,
                    line: 1,
                    column: 0,
                    errorType: "JSONParseError",
                  },
                ],
                call_graph: null,
              }); // reject 대신 오류 정보 resolve
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
            }); // reject 대신 오류 정보 resolve
          });
        } catch (e: any) {
          // spawn 전 오류 처리
          console.error("Error before spawning Python process:", e);
          outputChannel.appendLine(
            `ERROR before spawning Python: ${e.message}\n${e.stack}`
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
          }); // 오류 정보 resolve
        }
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
        // analyzeCode 내부 try...catch
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
                // withProgress 내부 try...catch
                progress.report({ message: "정적 분석 수행 중..." });
                analysisResult = await runAnalysisProcess(code, mode); // 결과 또는 오류 받기
                handleAnalysisResult(documentUri, config, analysisResult, mode);
                if (
                  analysisResult.errors.some((e) =>
                    e.errorType.endsWith("Error")
                  )
                ) {
                  outputChannel.appendLine(
                    `[analyzeCode] Analysis completed with errors (${mode}).`
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
                // runAnalysisProcess에서 reject된 경우 (거의 발생 안 함) 또는 withProgress 오류
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
                // 오류 발생 시에도 Problems 패널에 표시 시도
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
          // 실시간 분석 (Progress 없이)
          try {
            // 실시간 분석 try...catch
            analysisResult = await runAnalysisProcess(code, mode);
            handleAnalysisResult(documentUri, config, analysisResult, mode);
          } catch (error: any) {
            // runAnalysisProcess에서 reject된 경우
            console.error("Real-time analysis process failed:", error);
            outputChannel.appendLine(
              `[analyzeCode] Real-time analysis failed: ${error.message}`
            );
            // 실시간 분석 실패 시에도 Problems 패널에 표시 시도
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
      } catch (e: any) {
        // analyzeCode 자체 오류
        console.error("Error in analyzeCode function:", e);
        outputChannel.appendLine(
          `ERROR in analyzeCode: ${e.message}\n${e.stack}`
        );
      }
    }

    // --- 결과 처리 및 표시 함수 ---
    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult,
      mode: string
    ) {
      try {
        // handleAnalysisResult 내부 try...catch
        const errors: ErrorInfo[] = result.errors || [];
        outputChannel.appendLine(
          `[handleResult] Processing ${errors.length} diagnostics/errors.`
        );
        displayDiagnostics(documentUri, config, errors);

        const callGraphData = result.call_graph;
        if (
          callGraphData &&
          mode === "static" &&
          !errors.some((e) => e.errorType.endsWith("Error"))
        ) {
          outputChannel.appendLine(`[handleResult] Call graph data received:`);
          outputChannel.appendLine(JSON.stringify(callGraphData, null, 2));
          console.log("Call Graph Data:", callGraphData);
        }
      } catch (e: any) {
        console.error("Error handling analysis result:", e);
        outputChannel.appendLine(
          `ERROR handling analysis result: ${e.message}\n${e.stack}`
        );
        // 추가적인 오류 표시
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(0, 0, 0, 0),
          `Internal Error handling results: ${e.message}`,
          vscode.DiagnosticSeverity.Error
        );
        diagnostic.source = "FindRuntimeErr";
        diagnosticCollection.set(documentUri, [diagnostic]);
      }
    }

    function displayDiagnostics(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      errors: ErrorInfo[]
    ) {
      try {
        // displayDiagnostics 내부 try...catch
        outputChannel.appendLine(
          `[displayDiagnostics] Displaying ${errors.length} diagnostics.`
        );
        const diagnostics: vscode.Diagnostic[] = [];
        const decorationRanges: vscode.Range[] = [];

        errors.forEach((error) => {
          if (
            !error ||
            typeof error.message !== "string" ||
            typeof error.line !== "number" ||
            typeof error.column !== "number" ||
            typeof error.errorType !== "string"
          ) {
            outputChannel.appendLine(
              `[displayDiagnostics] Skipping invalid error object: ${JSON.stringify(
                error
              )}`
            );
            return;
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
          ].includes(error.errorType);
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
          const range = isInternalError
            ? new vscode.Range(0, 0, 0, 0)
            : new vscode.Range(
                line,
                column,
                line,
                Math.max(column + 1, column)
              );

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
            finalSeverity === vscode.DiagnosticSeverity.Error ||
            finalSeverity === vscode.DiagnosticSeverity.Warning
          ) {
            decorationRanges.push(range);
          }
        });

        diagnosticCollection.set(documentUri, diagnostics);

        const editor = vscode.window.activeTextEditor;
        if (
          editor &&
          editor.document.uri.toString() === documentUri.toString()
        ) {
          outputChannel.appendLine(
            `[displayDiagnostics] Setting decorations for ${decorationRanges.length} ranges.`
          );
          editor.setDecorations(errorDecorationType, decorationRanges);
        }
      } catch (e: any) {
        console.error("Error displaying diagnostics:", e);
        outputChannel.appendLine(
          `ERROR displaying diagnostics: ${e.message}\n${e.stack}`
        );
      }
    }

    function clearPreviousAnalysis(documentUri: vscode.Uri) {
      try {
        // clearPreviousAnalysis 내부 try...catch
        diagnosticCollection.delete(documentUri);
        const editor = vscode.window.activeTextEditor;
        if (
          editor &&
          editor.document.uri.toString() === documentUri.toString()
        ) {
          editor.setDecorations(errorDecorationType, []);
        }
      } catch (e: any) {
        console.error("Error clearing previous analysis:", e);
        outputChannel.appendLine(
          `ERROR clearing previous analysis: ${e.message}\n${e.stack}`
        );
      }
    }

    // --- 이벤트 리스너 ---
    vscode.workspace.onDidChangeTextDocument((event) => {
      try {
        outputChannel.appendLine("[onDidChangeTextDocument] Event fired.");
        if (event.document.languageId === "python") {
          if (debounceTimeout) {
            clearTimeout(debounceTimeout);
          }
          debounceTimeout = setTimeout(() => {
            outputChannel.appendLine(
              "[onDidChangeTextDocument] Debounced analysis triggered."
            );
            analyzeCode(
              event.document.getText(),
              event.document.uri,
              "realtime"
            );
            debounceTimeout = null;
          }, debounceDelay);
        }
      } catch (e: any) {
        console.error("Error in onDidChangeTextDocument handler:", e);
        outputChannel.appendLine(
          `ERROR in onDidChangeTextDocument: ${e.message}\n${e.stack}`
        );
      }
    });

    vscode.workspace.onDidOpenTextDocument((document) => {
      try {
        outputChannel.appendLine("[onDidOpenTextDocument] Event fired.");
        if (document.languageId === "python") {
          analyzeCode(document.getText(), document.uri, "realtime");
        }
      } catch (e: any) {
        console.error("Error in onDidOpenTextDocument handler:", e);
        outputChannel.appendLine(
          `ERROR in onDidOpenTextDocument: ${e.message}\n${e.stack}`
        );
      }
    });

    vscode.workspace.onDidChangeConfiguration((e) => {
      try {
        outputChannel.appendLine("[onDidChangeConfiguration] Event fired.");
        if (e.affectsConfiguration("findRuntimeErr")) {
          if (
            vscode.window.activeTextEditor &&
            vscode.window.activeTextEditor.document.languageId === "python"
          ) {
            analyzeCode(
              vscode.window.activeTextEditor.document.getText(),
              vscode.window.activeTextEditor.document.uri
            );
          }
        }
      } catch (e: any) {
        console.error("Error in onDidChangeConfiguration handler:", e);
        outputChannel.appendLine(
          `ERROR in onDidChangeConfiguration: ${e.message}\n${e.stack}`
        );
      }
    });

    // --- 명령어 등록 ---
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.analyzeCurrentFile",
        () => {
          try {
            outputChannel.appendLine(
              "[Command] findRuntimeErr.analyzeCurrentFile handler called."
            );
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document.languageId === "python") {
              analyzeCode(
                editor.document.getText(),
                editor.document.uri,
                "static",
                true
              );
            } else {
              vscode.window.showWarningMessage(
                "FindRuntimeErr: Please open a Python file to analyze."
              );
            }
          } catch (e: any) {
            console.error("Error in analyzeCurrentFile command handler:", e);
            outputChannel.appendLine(
              `ERROR in analyzeCurrentFile command: ${e.message}\n${e.stack}`
            );
          }
        }
      )
    );

    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.runDynamicAnalysis",
        () => {
          try {
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document.languageId === "python") {
              vscode.window.showInformationMessage(
                "FindRuntimeErr: Dynamic analysis is not yet implemented."
              );
            } else {
              vscode.window.showWarningMessage(
                "FindRuntimeErr: Please open a Python file to run dynamic analysis."
              );
            }
          } catch (e: any) {
            console.error("Error in runDynamicAnalysis command handler:", e);
            outputChannel.appendLine(
              `ERROR in runDynamicAnalysis command: ${e.message}\n${e.stack}`
            );
          }
        }
      )
    );

    // --- 초기 실행 ---
    if (
      vscode.window.activeTextEditor &&
      vscode.window.activeTextEditor.document.languageId === "python"
    ) {
      try {
        outputChannel.appendLine(
          "[Activate] Analyzing initially active Python file."
        );
        analyzeCode(
          vscode.window.activeTextEditor.document.getText(),
          vscode.window.activeTextEditor.document.uri
        );
      } catch (e: any) {
        console.error("Error during initial analysis:", e);
        outputChannel.appendLine(
          `ERROR during initial analysis: ${e.message}\n${e.stack}`
        );
      }
    }
  } catch (e: any) {
    // activate 함수 자체 오류 처리
    console.error("Error during extension activation:", e);
    // Output 채널이 생성되기 전일 수 있으므로 console.error만 사용
    vscode.window.showErrorMessage(
      `FindRuntimeErr failed to activate: ${e.message}`
    );
  }
} // activate 함수 끝

export function deactivate() {
  try {
    // deactivate 내부 try...catch
    outputChannel.dispose();
    console.log("FindRuntimeErr extension deactivated.");
  } catch (e: any) {
    console.error("Error during extension deactivation:", e);
  }
}
