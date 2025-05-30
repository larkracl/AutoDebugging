// src/extension.ts (필터링 로직 및 로그 강화)
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

    // --- 설정 가져오기 함수 ---
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
          .map((type) => type.toLowerCase()), // 설정값을 소문자로 저장
        minAnalysisLength: config.get<number>("minAnalysisLength", 10),
        pythonPath: config.get<string | null>("pythonPath", null),
      };
    }

    // --- Python 경로 결정 함수 ---
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
          } else {
            outputChannel.appendLine(
              `[getSelectedPythonPath] Path from settings is not a file or symlink: ${config.pythonPath}`
            );
          }
        } catch (e: any) {
          outputChannel.appendLine(
            `[getSelectedPythonPath] Path from settings is invalid: ${config.pythonPath} (Error: ${e.code})`
          );
        }
      } else {
        outputChannel.appendLine(
          `[getSelectedPythonPath] findRuntimeErr.pythonPath not set.`
        );
      }
      try {
        const pythonExtension =
          vscode.extensions.getExtension("ms-python.python");
        if (pythonExtension) {
          if (!pythonExtension.isActive) {
            await pythonExtension.activate();
          }
          const api = pythonExtension.exports;
          if (
            api?.environments?.resolveEnvironment &&
            api?.environments?.getActiveEnvironmentPath
          ) {
            const activeEnvPathDetails =
              api.environments.getActiveEnvironmentPath(resource);
            const activeEnvPath =
              typeof activeEnvPathDetails === "string"
                ? activeEnvPathDetails
                : activeEnvPathDetails?.path;
            if (activeEnvPath) {
              const environment = await api.environments.resolveEnvironment(
                activeEnvPath
              );
              const envPath = environment?.path;
              if (envPath) {
                try {
                  const stats = await fs.promises.stat(envPath);
                  if (stats.isFile() || stats.isSymbolicLink()) {
                    outputChannel.appendLine(
                      `[getSelectedPythonPath] Using Python path from Python extension API (environments): ${envPath}`
                    );
                    return envPath;
                  } else {
                    outputChannel.appendLine(
                      `[getSelectedPythonPath] Env path is not a file or symlink: ${envPath}`
                    );
                  }
                } catch (e: any) {
                  outputChannel.appendLine(
                    `[getSelectedPythonPath] Env path is invalid: ${envPath} (Error: ${e.code})`
                  );
                }
              } else {
                outputChannel.appendLine(
                  `[getSelectedPythonPath] Could not resolve environment path from active path: ${activeEnvPath}`
                );
              }
            } else {
              outputChannel.appendLine(
                `[getSelectedPythonPath] No active environment path returned by Python extension.`
              );
            }
          } else if (api?.settings?.getExecutionDetails) {
            const execDetails = api.settings.getExecutionDetails(resource);
            const potentialPath = execDetails?.execCommand?.[0];
            if (potentialPath) {
              try {
                const stats = await fs.promises.stat(potentialPath);
                if (stats.isFile() || stats.isSymbolicLink()) {
                  outputChannel.appendLine(
                    `[getSelectedPythonPath] Using Python path from Python extension API (settings): ${potentialPath}`
                  );
                  return potentialPath;
                } else {
                  outputChannel.appendLine(
                    `[getSelectedPythonPath] Settings path is not a file or symlink: ${potentialPath}`
                  );
                }
              } catch (e: any) {
                outputChannel.appendLine(
                  `[getSelectedPythonPath] Settings path is invalid: ${potentialPath} (Error: ${e.code})`
                );
              }
            } else {
              outputChannel.appendLine(
                `[getSelectedPythonPath] Could not get valid execution details from settings API.`
              );
            }
          } else {
            outputChannel.appendLine(
              "[getSelectedPythonPath] Python extension API (environments/settings) not available."
            );
          }
        } else {
          outputChannel.appendLine(
            "[getSelectedPythonPath] VSCode Python extension (ms-python.python) not found."
          );
        }
      } catch (err: any) {
        outputChannel.appendLine(
          `[getSelectedPythonPath] Error accessing Python extension API: ${err.message}\n${err.stack}`
        );
      }
      const defaultPath = vscode.workspace
        .getConfiguration("python", resource)
        .get<string>("defaultInterpreterPath");
      if (defaultPath) {
        try {
          const stats = await fs.promises.stat(defaultPath);
          if (stats.isFile() || stats.isSymbolicLink()) {
            outputChannel.appendLine(
              `[getSelectedPythonPath] Using python.defaultInterpreterPath: ${defaultPath}`
            );
            return defaultPath;
          } else {
            outputChannel.appendLine(
              `[getSelectedPythonPath] defaultInterpreterPath is not a file or symlink: ${defaultPath}`
            );
          }
        } catch (e: any) {
          outputChannel.appendLine(
            `[getSelectedPythonPath] defaultInterpreterPath is invalid: ${defaultPath} (Error: ${e.code})`
          );
        }
      } else {
        outputChannel.appendLine(
          `[getSelectedPythonPath] python.defaultInterpreterPath not set.`
        );
      }
      outputChannel.appendLine(
        "[getSelectedPythonPath] Falling back to 'python3' or 'python' command from PATH."
      );
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
      outputChannel.appendLine(
        "[getSelectedPythonPath] Could not find any valid Python interpreter."
      );
      throw new Error(
        "Could not find a valid Python interpreter. Configure 'findRuntimeErr.pythonPath', 'python.defaultInterpreterPath', or ensure Python is in PATH."
      );
    }

    // --- Python 패키지 검사 함수 ---
    function checkPythonPackages(pythonExecutable: string): {
      missing: string[];
      error?: string;
    } {
      const requiredPackages = ["parso", "astroid", "networkx"];
      const missingPackages: string[] = [];
      let checkError: string | undefined;
      outputChannel.appendLine(
        `[checkPackages] Checking for: ${requiredPackages.join(
          ", "
        )} using ${pythonExecutable}`
      );
      for (const pkg of requiredPackages) {
        try {
          const command = `"${pythonExecutable}" -m pip show "${pkg}"`;
          outputChannel.appendLine(`[checkPackages] Running: ${command}`);
          execSync(command, { stdio: "pipe", encoding: "utf-8" });
          outputChannel.appendLine(`[checkPackages] Package found: ${pkg}`);
        } catch (error: any) {
          outputChannel.appendLine(
            `[checkPackages] Package not found or error checking: ${pkg}. Exit Code: ${error.status}`
          );
          const stderr = error.stderr?.toString("utf-8") || "";
          const stdout = error.stdout?.toString("utf-8") || "";
          if (stderr)
            outputChannel.appendLine(
              `[checkPackages] Stderr: ${stderr.substring(0, 200)}...`
            );
          if (stdout)
            outputChannel.appendLine(
              `[checkPackages] Stdout: ${stdout.substring(0, 200)}...`
            );
          missingPackages.push(pkg);
          const errorMsg = stderr || stdout || error.message || "";
          if (
            error.status === 127 ||
            errorMsg.includes("No such file or directory") ||
            errorMsg.includes("command not found") ||
            errorMsg.includes("not recognized")
          ) {
            checkError = `Failed to run Python ('${pythonExecutable}'). Is the path correct and Python installed?`;
            outputChannel.appendLine(
              `[checkPackages] Critical Python execution failure: ${checkError}`
            );
            break;
          }
        }
      }
      return { missing: missingPackages, error: checkError };
    }

    // --- 정적 분석 프로세스 실행 함수 ---
    async function runAnalysisProcess(
      code: string,
      mode: "realtime" | "static",
      documentUri?: vscode.Uri
    ): Promise<AnalysisResult> {
      let pythonExecutable: string;
      try {
        pythonExecutable = await getSelectedPythonPath(documentUri);
      } catch (e: any) {
        outputChannel.appendLine(
          `[runAnalysisProcess] Failed to get Python path: ${e.message}`
        );
        return Promise.resolve({
          errors: [
            {
              message: `Failed to determine Python path: ${e.message}`,
              line: 1,
              column: 0,
              to_line: 1,
              end_column: 1,
              errorType: "PythonPathError",
            },
          ],
          call_graph: null,
        });
      }
      if (lastUsedPythonExecutable !== pythonExecutable) {
        outputChannel.appendLine(
          `[runAnalysisProcess] Using Python: ${pythonExecutable}`
        );
        lastUsedPythonExecutable = pythonExecutable;
        checkedPackages = false;
      }
      return new Promise((resolve) => {
        try {
          let proceedAnalysis = !checkedPackages;
          if (proceedAnalysis) {
            outputChannel.appendLine(
              `[runAnalysisProcess] Checking required packages...`
            );
            const checkResult = checkPythonPackages(pythonExecutable);
            if (checkResult.error || checkResult.missing.length > 0) {
              const errorMsg =
                checkResult.error ||
                `FindRuntimeErr requires: ${checkResult.missing.join(
                  ", "
                )}. Please run 'pip install parso astroid networkx' in '${pythonExecutable}'. Analysis skipped.`;
              const errorType = checkResult.error
                ? "PythonPathError"
                : "MissingDependencyError";
              resolve({
                errors: [
                  {
                    message: errorMsg,
                    line: 1,
                    column: 0,
                    to_line: 1,
                    end_column: 1,
                    errorType: errorType,
                  },
                ],
                call_graph: null,
              });
              checkedPackages = true;
              return;
            }
            checkedPackages = true;
            outputChannel.appendLine(
              `[runAnalysisProcess] Required packages check passed.`
            );
          } else {
            outputChannel.appendLine(
              `[runAnalysisProcess] Skipping package check (already passed).`
            );
          }

          const scriptPath = path.join(
            context.extensionPath,
            "scripts",
            "main.py"
          );
          if (!fs.existsSync(scriptPath)) {
            throw new Error(`Analysis script main.py not found: ${scriptPath}`);
          }
          const spawnOptions: SpawnOptionsWithoutStdio = {
            cwd: path.dirname(scriptPath),
          };
          outputChannel.appendLine(
            `[runAnalysisProcess] Spawning: "${pythonExecutable}" "${scriptPath}" ${mode}`
          );
          const pythonProcess = spawn(
            pythonExecutable,
            [scriptPath, mode],
            spawnOptions
          );
          let stdoutData = "";
          let stderrData = "";
          pythonProcess.stdin.write(code, "utf-8");
          pythonProcess.stdin.end();
          outputChannel.appendLine(
            `[runAnalysisProcess] Sent code (${Buffer.byteLength(
              code,
              "utf-8"
            )} bytes) to Python stdin.`
          );
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
            try {
              outputChannel.appendLine(
                `[runAnalysisProcess] Python process exited with code: ${closeCode}`
              );
              // **** 추가된 로그: stderr 전체 내용 확인 ****
              if (stderrData.trim()) {
                outputChannel.appendLine(
                  `[runAnalysisProcess] Full Stderr from Python:\n${stderrData}`
                );
              }

              // 종료 코드가 0이 아니거나 stderr에 (오류성) 내용이 있으면 오류로 간주
              // (Python 스크립트가 오류 시에도 JSON을 출력할 수 있으므로, closeCode만으로 판단하지 않음)
              if (
                closeCode !== 0 ||
                (stderrData.trim() &&
                  !stderrData.includes("[Linter.") &&
                  !stderrData.includes("Parso AST parsed") &&
                  !stderrData.includes("Found") &&
                  !stderrData.includes("analyze_code returning result"))
              ) {
                // 순수 오류 stderr만 고려
                let errorDetail = `Analysis script failed (Code: ${closeCode}).`;
                let errorType = "AnalysisScriptError";
                let errorLine = 1,
                  errorColumn = 0,
                  errorToLine = 1,
                  errorEndColumn = 1;

                // stdout에 JSON 형태의 오류가 있을 수 있음 (Python 스크립트가 실패 시 출력)
                try {
                  if (stdoutData.trim()) {
                    const errorResult = JSON.parse(stdoutData); // 여기서 stdoutData는 전체여야 함
                    if (errorResult?.errors?.[0]) {
                      const firstError = errorResult.errors[0];
                      if (
                        firstError.message &&
                        typeof firstError.line === "number" &&
                        typeof firstError.column === "number"
                      ) {
                        errorDetail = firstError.message;
                        errorType = firstError.errorType || errorType;
                        errorLine = firstError.line;
                        errorColumn = firstError.column;
                        errorToLine = firstError.to_line || errorLine;
                        errorEndColumn =
                          firstError.end_column || errorColumn + 1;
                      }
                    }
                  }
                } catch (e) {
                  outputChannel.appendLine(
                    `[runAnalysisProcess] Failed to parse stdout as error JSON: ${e}`
                  );
                }
                const trimmedStderr = stderrData.trim();
                if (
                  trimmedStderr &&
                  !errorDetail.includes(trimmedStderr.substring(0, 100))
                ) {
                  errorDetail += `\nStderr: ${trimmedStderr.substring(
                    0,
                    500
                  )}...`;
                }
                resolve({
                  errors: [
                    {
                      message: errorDetail,
                      line: errorLine,
                      column: errorColumn,
                      to_line: errorToLine,
                      end_column: errorEndColumn,
                      errorType: errorType,
                    },
                  ],
                  call_graph: null,
                });
                return;
              }

              // 정상 종료 시 stdout 데이터 처리
              const trimmedStdout = stdoutData.trim();
              // **** 수정된 로그: 파싱 *전*의 trimmedStdout 전체를 출력 ****
              outputChannel.appendLine(
                `[runAnalysisProcess] Raw stdout before JSON.parse (Mode: ${mode}):\n${trimmedStdout}`
              );

              if (!trimmedStdout) {
                resolve({ errors: [], call_graph: null });
                return;
              }

              // JSON 파싱 시도
              let result: AnalysisResult;
              try {
                result = JSON.parse(trimmedStdout);
              } catch (parseError: any) {
                // JSON 파싱 자체 실패 시
                outputChannel.appendLine(
                  `[runAnalysisProcess] Error parsing analysis results: ${
                    parseError.message
                  }. Raw: ${trimmedStdout.substring(0, 500)}...`
                ); // 로그 길이 증가
                resolve({
                  errors: [
                    {
                      message: `Error parsing analysis results: ${parseError.message}`,
                      line: 1,
                      column: 0,
                      to_line: 1,
                      end_column: 1,
                      errorType: "JSONParseError",
                    },
                  ],
                  call_graph: null,
                });
                return;
              }

              // **** 추가된 로그: 파싱 *후*의 result.errors 배열 길이 확인 ****
              outputChannel.appendLine(
                `[runAnalysisProcess] Parsed result.errors.length: ${
                  result?.errors?.length ?? "undefined"
                }`
              );

              // 결과 형식 검증
              if (
                result &&
                Array.isArray(result.errors) &&
                "call_graph" in result
              ) {
                resolve(result);
              } else {
                outputChannel.appendLine(
                  `[runAnalysisProcess] Invalid analysis result format after parse: ${JSON.stringify(
                    result
                  ).substring(0, 200)}...`
                );
                resolve({
                  errors: [
                    {
                      message:
                        "Invalid analysis result format received after successful parse.",
                      line: 1,
                      column: 0,
                      to_line: 1,
                      end_column: 1,
                      errorType: "InvalidFormatError",
                    },
                  ],
                  call_graph: null,
                });
              }
            } catch (processCloseError: any) {
              // on('close') 콜백 자체의 오류 처리
              outputChannel.appendLine(
                `[runAnalysisProcess] Error in on('close') handler: ${processCloseError.message}`
              );
              resolve({
                errors: [
                  {
                    message: `Internal error processing analysis result: ${processCloseError.message}`,
                    line: 1,
                    column: 0,
                    to_line: 1,
                    end_column: 1,
                    errorType: "InternalCloseHandlerError",
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
                  to_line: 1,
                  end_column: 1,
                  errorType: "SpawnError",
                },
              ],
              call_graph: null,
            });
          });
        } catch (e: any) {
          console.error("Error in runAnalysisProcess setup:", e);
          outputChannel.appendLine(
            `ERROR in runAnalysisProcess setup: ${e.message}\n${e.stack}`
          );
          resolve({
            errors: [
              {
                message: `Error setting up analysis process: ${e.message}`,
                line: 1,
                column: 0,
                to_line: 1,
                end_column: 1,
                errorType: "SetupError",
              },
            ],
            call_graph: null,
          });
        }
      });
    }

    // --- 동적 분석 프로세스 실행 함수 ---
    async function runDynamicAnalysisProcess(
      code: string,
      documentUri?: vscode.Uri
    ): Promise<AnalysisResult> {
      outputChannel.appendLine(
        `[runDynamicAnalysisProcess] Starting dynamic analysis...`
      );
      let pythonExecutable: string;
      try {
        pythonExecutable = await getSelectedPythonPath(documentUri);
      } catch (e: any) {
        outputChannel.appendLine(
          `[runDynamicAnalysisProcess] Failed to get Python path: ${e.message}`
        );
        return Promise.resolve({
          errors: [
            {
              message: `Dynamic Analysis Failed: Python path error - ${e.message}`,
              line: 1,
              column: 0,
              to_line: 1,
              end_column: 1,
              errorType: "PythonPathErrorDA",
            },
          ],
          call_graph: null,
        });
      }
      const scriptPath = path.join(
        context.extensionPath,
        "scripts",
        "dynamic_analyze.py"
      );
      if (!fs.existsSync(scriptPath)) {
        outputChannel.appendLine(
          `[runDynamicAnalysisProcess] Error: dynamic_analyze.py not found: ${scriptPath}`
        );
        return Promise.resolve({
          errors: [
            {
              message: `Dynamic Analysis Failed: Script not found.`,
              line: 1,
              column: 0,
              to_line: 1,
              end_column: 1,
              errorType: "ScriptNotFoundErrorDA",
            },
          ],
          call_graph: null,
        });
      }
      const env = { ...process.env };
      return new Promise((resolve) => {
        const spawnOptions: SpawnOptionsWithoutStdio = {
          cwd: path.dirname(scriptPath),
          env: env,
        };
        outputChannel.appendLine(
          `[runDynamicAnalysisProcess] Spawning: "${pythonExecutable}" "${scriptPath}"`
        );
        const process = spawn(pythonExecutable, [scriptPath], spawnOptions);
        let stdoutData = "";
        let stderrData = "";
        process.stdin.write(code, "utf-8");
        process.stdin.end();
        process.stdout.on("data", (data) => {
          stdoutData += data.toString("utf-8");
        });
        process.stderr.on("data", (data) => {
          const chunk = data.toString("utf-8");
          stderrData += chunk;
          chunk.split("\n").forEach((line: string) => {
            if (line.trim())
              outputChannel.appendLine(`[Dynamic Py Stderr] ${line}`);
          });
        });
        process.on("close", (closeCode) => {
          outputChannel.appendLine(
            `[runDynamicAnalysisProcess] Process exited with code: ${closeCode}`
          );
          if (closeCode !== 0 || stderrData.trim()) {
            const errorMsg = `Dynamic analysis script failed (Code: ${closeCode}). ${stderrData
              .trim()
              .substring(0, 500)}...`;
            outputChannel.appendLine(
              `[runDynamicAnalysisProcess] Error: ${errorMsg}`
            );
            resolve({
              errors: [
                {
                  message: errorMsg,
                  line: 1,
                  column: 0,
                  to_line: 1,
                  end_column: 1,
                  errorType: "DynamicScriptError",
                },
              ],
              call_graph: null,
            });
            return;
          }
          const trimmedStdout = stdoutData.trim();
          if (!trimmedStdout) {
            resolve({ errors: [], call_graph: null });
            return;
          }
          try {
            const result: Omit<AnalysisResult, "call_graph"> & {
              call_graph?: null;
            } = JSON.parse(trimmedStdout);
            if (result && Array.isArray(result.errors)) {
              resolve({ errors: result.errors, call_graph: null });
            } else {
              outputChannel.appendLine(
                `[runDynamicAnalysisProcess] Invalid result format: ${trimmedStdout.substring(
                  0,
                  200
                )}...`
              );
              resolve({
                errors: [
                  {
                    message: "Invalid dynamic analysis result format.",
                    line: 1,
                    column: 0,
                    to_line: 1,
                    end_column: 1,
                    errorType: "InvalidFormatErrorDA",
                  },
                ],
                call_graph: null,
              });
            }
          } catch (e: any) {
            outputChannel.appendLine(
              `[runDynamicAnalysisProcess] Error parsing result: ${e}. Raw: ${trimmedStdout.substring(
                0,
                200
              )}...`
            );
            resolve({
              errors: [
                {
                  message: `Error parsing dynamic analysis result: ${e.message}`,
                  line: 1,
                  column: 0,
                  to_line: 1,
                  end_column: 1,
                  errorType: "JSONParseErrorDA",
                },
              ],
              call_graph: null,
            });
          }
        });
        process.on("error", (err) => {
          outputChannel.appendLine(
            `[runDynamicAnalysisProcess] Failed to start process: ${err.message}`
          );
          resolve({
            errors: [
              {
                message: `Failed to start dynamic analysis process: ${err.message}`,
                line: 1,
                column: 0,
                to_line: 1,
                end_column: 1,
                errorType: "SpawnErrorDA",
              },
            ],
            call_graph: null,
          });
        });
      });
    }

    // --- 실시간 분석 실행 함수 ---
    async function analyzeCodeRealtime(
      document: vscode.TextEditor["document"]
    ) {
      try {
        const code = document.getText();
        const documentUri = document.uri;
        const config = getConfiguration();
        if (!config.enable) {
          clearPreviousAnalysis(documentUri);
          return;
        }
        if (code.length < config.minAnalysisLength) {
          clearPreviousAnalysis(documentUri);
          return;
        }
        clearPreviousAnalysis(documentUri);
        const analysisResult = await runAnalysisProcess(
          code,
          "realtime",
          documentUri
        );
        lastCallGraph = analysisResult.call_graph;
        handleAnalysisResult(documentUri, config, analysisResult, "realtime");
      } catch (e: any) {
        console.error("Error in analyzeCodeRealtime:", e);
        outputChannel.appendLine(
          `ERROR in analyzeCodeRealtime: ${e.message}\n${e.stack}`
        );
        handleAnalysisResult(
          document.uri,
          getConfiguration(),
          {
            errors: [
              {
                message: `Unexpected real-time analysis error: ${e.message}`,
                line: 1,
                column: 0,
                to_line: 1,
                end_column: 1,
                errorType: "RealtimeAnalysisError",
              },
            ],
            call_graph: null,
          },
          "realtime"
        );
      }
    }

    // --- 결과 처리 및 표시 함수들 ---
    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult,
      mode: "realtime" | "static" | "dynamic"
    ) {
      if (!result || !Array.isArray(result.errors)) {
        outputChannel.appendLine(
          `[handleAnalysisResult] Invalid result/errors for ${mode} @ ${documentUri.fsPath}.`
        );
        if (mode === "realtime") {
          clearPreviousAnalysis(documentUri);
        }
        return;
      }
      outputChannel.appendLine(
        `[handleAnalysisResult] Received ${result.errors.length} errors (before filtering) for ${documentUri.fsPath} (Mode: ${mode}):`
      );
      result.errors.forEach((err, index) => {
        // 로그 추가: 모든 수신된 오류 표시
        outputChannel.appendLine(
          `  [RawErr ${index + 1}] Type: ${err.errorType}, Line: ${
            err.line
          }, Col: ${err.column}, Msg: ${err.message.substring(0, 70)}...`
        );
      });

      const filteredErrors = result.errors.filter((err) => {
        const isValidErrorObject =
          err &&
          typeof err.message === "string" &&
          typeof err.line === "number" &&
          typeof err.column === "number" &&
          typeof err.errorType === "string";
        if (!isValidErrorObject) {
          outputChannel.appendLine(
            `[handleAnalysisResult] Invalid error object found: ${JSON.stringify(
              err
            )}`
          );
          return false;
        }
        const isIgnored = config.ignoredErrorTypes.includes(
          err.errorType.toLowerCase()
        );
        if (isIgnored) {
          outputChannel.appendLine(
            `[handleAnalysisResult] Ignored error by type: ${err.errorType}`
          );
        }
        return !isIgnored;
      });
      outputChannel.appendLine(
        `[handleAnalysisResult] ${filteredErrors.length} errors after 'ignoredErrorTypes' filtering.`
      );
      filteredErrors.forEach((err, index) => {
        outputChannel.appendLine(
          `  [FilteredErr ${index + 1}] Type: ${err.errorType}, Line: ${
            err.line
          }, Col: ${err.column}, Msg: ${err.message.substring(0, 70)}...`
        );
      });

      displayDiagnostics(documentUri, config, filteredErrors);
      if (mode === "static" && result.call_graph) {
        outputChannel.appendLine(
          `[handleAnalysisResult] Call graph: ${result.call_graph.nodes.length} nodes, ${result.call_graph.links.length} links.`
        );
      }
    }

    function getSeverityAndUnderline(
      errorType: string,
      config: ExtensionConfig
    ): { severity: vscode.DiagnosticSeverity; underline: boolean } {
      const lowerType = errorType.toLowerCase();
      let severity = vscode.DiagnosticSeverity.Error;
      let underline = false;
      const checkerErrorPattern = /^[ew]\d{4}$/i; // E/W + 숫자 4개

      if (lowerType === "syntaxerror") {
        severity = vscode.DiagnosticSeverity.Error;
        underline = true;
      } else if (checkerErrorPattern.test(errorType)) {
        severity = errorType.toUpperCase().startsWith("W")
          ? vscode.DiagnosticSeverity.Warning
          : vscode.DiagnosticSeverity.Error;
        underline = true;
      } else if (lowerType === "dynamictestfailure") {
        severity = vscode.DiagnosticSeverity.Error;
        underline = true;
      } else if (
        lowerType.includes("error") &&
        (lowerType.includes("internal") ||
          lowerType.includes("path") ||
          lowerType.includes("dependency") ||
          lowerType.includes("script") ||
          lowerType.includes("parse") ||
          lowerType.includes("json") ||
          lowerType.includes("spawn") ||
          lowerType.includes("setup") ||
          lowerType.includes("analysis") ||
          lowerType.includes("crash") ||
          lowerType.includes("traversal") ||
          lowerType.includes("graph") ||
          lowerType.endsWith("da") ||
          lowerType === "modeerror" ||
          lowerType === "checkeriniterror")
      ) {
        severity = vscode.DiagnosticSeverity.Error;
        underline = false;
      } else if (lowerType.includes("error")) {
        severity = vscode.DiagnosticSeverity.Error;
        underline = false;
      } else {
        severity = vscode.DiagnosticSeverity.Information;
        underline = false;
      }
      // config.severityLevel 적용은 displayDiagnostics에서 함
      return { severity, underline };
    }

    function displayDiagnostics(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      errors: ErrorInfo[]
    ) {
      const diagnostics: vscode.Diagnostic[] = [];
      const decorations: vscode.DecorationOptions[] = [];
      let displayedCount = 0;

      const createRange = (err: ErrorInfo): vscode.Range => {
        const line = Math.max(0, err.line - 1);
        const column = Math.max(0, err.column); // Parso/Astroid 0-based 가정
        const toLine = Math.max(
          line,
          (err.to_line != null ? err.to_line : err.line) - 1
        );
        const endColumn = Math.max(
          column + 1,
          err.end_column != null ? err.end_column : column + 1
        );
        if (toLine < line || (toLine === line && endColumn <= column)) {
          outputChannel.appendLine(
            `[createRange] Corrected invalid range for ${err.errorType}: L${err.line}C${err.column}`
          );
          return new vscode.Range(line, column, line, column + 1);
        }
        return new vscode.Range(line, column, toLine, endColumn);
      };

      errors.forEach((err) => {
        try {
          const range = createRange(err);
          const { severity, underline } = getSeverityAndUnderline(
            err.errorType,
            config
          );
          if (severity <= config.severityLevel) {
            // Error(0) .. Hint(3). 설정값보다 심각도가 높거나 같으면 표시
            const diagnostic = new vscode.Diagnostic(
              range,
              err.message,
              severity
            );
            diagnostic.source = "FindRuntimeErr";
            diagnostic.code = err.errorType;
            diagnostics.push(diagnostic);
            displayedCount++;
            if (underline) {
              decorations.push({ range: range });
            }
          } else {
            outputChannel.appendLine(
              `[displayDiagnostics] Ignored by severity setting: ${err.errorType} (Severity: ${severity}, Config: ${config.severityLevel})`
            );
          }
        } catch (e: any) {
          outputChannel.appendLine(
            `[displayDiagnostics] Error processing item: ${JSON.stringify(
              err
            )} - ${e.message}`
          );
        }
      });
      outputChannel.appendLine(
        `[displayDiagnostics] Displaying ${displayedCount} diagnostics out of ${errors.length} filtered errors.`
      );
      diagnosticCollection.set(documentUri, diagnostics);
      const editor = vscode.window.visibleTextEditors.find(
        (e) => e.document.uri.toString() === documentUri.toString()
      );
      if (editor) {
        editor.setDecorations(errorDecorationType, decorations);
      } else {
        outputChannel.appendLine(
          `[displayDiagnostics] Editor not visible for ${documentUri.fsPath}. Decorations not applied.`
        );
      }
    }

    function clearPreviousAnalysis(documentUri: vscode.Uri) {
      diagnosticCollection.delete(documentUri);
      const editor = vscode.window.visibleTextEditors.find(
        (e) => e.document.uri.toString() === documentUri.toString()
      );
      if (editor) {
        editor.setDecorations(errorDecorationType, []);
      }
    }

    // --- Hover Provider ---
    const hoverProvider = vscode.languages.registerHoverProvider(
      { language: "python", scheme: "file" },
      {
        provideHover(
          document,
          position,
          token
        ): vscode.ProviderResult<vscode.Hover> {
          try {
            const diagnostics = diagnosticCollection.get(document.uri);
            if (!diagnostics || diagnostics.length === 0) return undefined;
            const diagnosticsAtPos = diagnostics
              .filter((d) => d.range.contains(position))
              .sort((a, b) => {
                // 더 넓은 범위(더 많은 줄/컬럼을 포함하는 진단)를 우선적으로 표시
                const aLines = a.range.end.line - a.range.start.line;
                const bLines = b.range.end.line - b.range.start.line;
                if (aLines !== bLines) return bLines - aLines;
                const aChars = a.range.end.character - a.range.start.character;
                const bChars = b.range.end.character - b.range.start.character;
                return bChars - aChars;
              });
            if (diagnosticsAtPos.length === 0) return undefined;
            const hoverContent = new vscode.MarkdownString("", true);
            hoverContent.supportHtml = true;
            diagnosticsAtPos.slice(0, 5).forEach((diagnostic, index) => {
              if (index > 0) hoverContent.appendMarkdown("\n\n---\n\n");
              hoverContent.appendMarkdown(
                `**[${diagnostic.code || "FindRuntimeErr"}]** ${diagnostic.message}`
              );
            });
            const hoverRange = diagnosticsAtPos[0].range;
            return new vscode.Hover(hoverContent, hoverRange);
          } catch (e: any) {
            outputChannel.appendLine(
              `ERROR in HoverProvider: ${e.message}\n${e.stack}`
            );
            return undefined;
          }
        },
      }
    );
    context.subscriptions.push(hoverProvider);

    // --- 이벤트 리스너 등록 ---
    const triggerRealtimeAnalysis = (document: vscode.TextDocument) => {
      if (document.languageId !== "python" || document.uri.scheme !== "file")
        return;
      if (debounceTimeout) clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        analyzeCodeRealtime(document).catch((e) => {
          console.error("Error in analyzeCodeRealtime (triggered):", e);
          outputChannel.appendLine(
            `ERROR in analyzeCodeRealtime (triggered): ${e.message}`
          );
        });
      }, debounceDelay);
    };
    context.subscriptions.push(
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (
          vscode.window.activeTextEditor &&
          event.document === vscode.window.activeTextEditor.document
        ) {
          triggerRealtimeAnalysis(event.document);
        }
      })
    );
    context.subscriptions.push(
      vscode.workspace.onDidOpenTextDocument((document) => {
        if (
          document.languageId === "python" &&
          document.uri.scheme === "file"
        ) {
          analyzeCodeRealtime(document).catch((e) => {});
        }
      })
    );
    context.subscriptions.push(
      vscode.workspace.onDidCloseTextDocument((document) => {
        if (document.languageId === "python") {
          clearPreviousAnalysis(document.uri);
        }
      })
    );
    context.subscriptions.push(
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (
          editor &&
          editor.document.languageId === "python" &&
          editor.document.uri.scheme === "file"
        ) {
          triggerRealtimeAnalysis(editor.document);
        }
      })
    );
    context.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        let needsReanalysis = false;
        let resetPackageCheck = false;
        if (e.affectsConfiguration("findRuntimeErr")) {
          outputChannel.appendLine(
            "[Config Change] findRuntimeErr config changed."
          );
          if (e.affectsConfiguration("findRuntimeErr.pythonPath")) {
            resetPackageCheck = true;
          }
          needsReanalysis = true;
        }
        if (e.affectsConfiguration("python.defaultInterpreterPath")) {
          outputChannel.appendLine(
            "[Config Change] python.defaultInterpreterPath changed."
          );
          resetPackageCheck = true;
          needsReanalysis = true;
        }
        if (resetPackageCheck) {
          checkedPackages = false;
          outputChannel.appendLine("Package check status reset.");
        }
        if (
          needsReanalysis &&
          vscode.window.activeTextEditor &&
          vscode.window.activeTextEditor.document.languageId === "python"
        ) {
          outputChannel.appendLine("[Config Change] Triggering re-analysis.");
          analyzeCodeRealtime(vscode.window.activeTextEditor.document).catch(
            (e) => {}
          );
        }
      })
    );

    // --- 명령어 등록 ---
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.analyzeCurrentFile",
        async () => {
          try {
            const editor = vscode.window.activeTextEditor;
            if (editor?.document.languageId === "python") {
              outputChannel.appendLine(
                "[Command] analyzeCurrentFile triggered."
              );
              clearPreviousAnalysis(editor.document.uri);
              const config = getConfiguration();
              await vscode.window.withProgress(
                {
                  location: vscode.ProgressLocation.Notification,
                  title: "FindRuntimeErr: 정적 분석 중...",
                  cancellable: false,
                },
                async (progress) => {
                  progress.report({ message: "코드 분석 중..." });
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
                    `FindRuntimeErr: 정적 분석 완료. ${result.errors.length}개 이슈 발견.`
                  );
                }
              );
            } else {
              vscode.window.showWarningMessage(
                "정적 분석할 Python 파일을 여세요."
              );
            }
          } catch (e: any) {
            outputChannel.appendLine(
              `[Command Error] analyzeCurrentFile: ${e.message}\n${e.stack}`
            );
            vscode.window.showErrorMessage(`정적 분석 오류: ${e.message}`);
          }
        }
      )
    );
    context.subscriptions.push(
      vscode.commands.registerCommand(
        "findRuntimeErr.runDynamicAnalysis",
        async () => {
          try {
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document.languageId === "python") {
              outputChannel.appendLine(
                "[Command] runDynamicAnalysis triggered."
              );
              const config = getConfiguration();
              if (!config.enableDynamicAnalysis) {
                vscode.window.showInformationMessage(
                  "FindRuntimeErr: 동적 분석 비활성화됨 ('findRuntimeErr.enableDynamicAnalysis')."
                );
                return;
              }
              clearPreviousAnalysis(editor.document.uri);
              await vscode.window.withProgress(
                {
                  location: vscode.ProgressLocation.Notification,
                  title: "FindRuntimeErr: 동적 분석 중...",
                  cancellable: false,
                },
                async (progress) => {
                  progress.report({ message: "테스트 실행 및 분석 중..." });
                  const result = await runDynamicAnalysisProcess(
                    editor.document.getText(),
                    editor.document.uri
                  );
                  handleAnalysisResult(
                    editor.document.uri,
                    config,
                    result,
                    "dynamic"
                  );
                  vscode.window.showInformationMessage(
                    `FindRuntimeErr: 동적 분석 완료. ${result.errors.length}개 오류/실패 발견.`
                  );
                }
              );
            } else {
              vscode.window.showWarningMessage(
                "동적 분석할 Python 파일을 여세요."
              );
            }
          } catch (e: any) {
            outputChannel.appendLine(
              `[Command Error] runDynamicAnalysis: ${e.message}\n${e.stack}`
            );
            vscode.window.showErrorMessage(`동적 분석 오류: ${e.message}`);
          }
        }
      )
    );

    // --- 초기 실행 ---
    async function runInitialAnalysis() {
      const editor = vscode.window.activeTextEditor;
      if (
        editor &&
        editor.document.languageId === "python" &&
        editor.document.uri.scheme === "file"
      ) {
        outputChannel.appendLine(
          "[Activate] Running initial analysis for active Python file."
        );
        try {
          const initialConfig = getConfiguration();
          const initialPython = await getSelectedPythonPath(
            editor.document.uri
          );
          const pkgsCheck = checkPythonPackages(initialPython);
          if (pkgsCheck.error || pkgsCheck.missing.length > 0) {
            const errorMsg =
              pkgsCheck.error ||
              `Missing packages: ${pkgsCheck.missing.join(
                ", "
              )}. Run 'pip install parso astroid networkx'`;
            const errorType = pkgsCheck.error
              ? "PythonPathError"
              : "MissingDependencyError";
            displayDiagnostics(editor.document.uri, initialConfig, [
              {
                message: errorMsg,
                line: 1,
                column: 0,
                to_line: 1,
                end_column: 1,
                errorType: errorType,
              },
            ]);
            checkedPackages = true;
          } else {
            checkedPackages = true;
            await analyzeCodeRealtime(editor.document);
          }
        } catch (e: any) {
          console.error("Error during initial analysis:", e);
          outputChannel.appendLine(
            `ERROR during initial analysis: ${e.message}\n${e.stack}`
          );
          if (editor) {
            displayDiagnostics(editor.document.uri, getConfiguration(), [
              {
                message: `Initial analysis error: ${e.message}`,
                line: 1,
                column: 0,
                to_line: 1,
                end_column: 1,
                errorType: "InitialAnalysisError",
              },
            ]);
          }
        }
      } else {
        outputChannel.appendLine(
          "[Activate] No active local Python editor for initial analysis."
        );
      }
    }
    runInitialAnalysis().catch((e) => {
      console.error("Error executing runInitialAnalysis:", e);
      outputChannel?.appendLine(
        `ERROR executing runInitialAnalysis: ${e.message}`
      );
    });
  } catch (e: any) {
    console.error("FATAL Error during extension activation:", e);
    vscode.window.showErrorMessage(
      `FindRuntimeErr failed to activate: ${e.message}. Check output channel.`
    );
    if (outputChannel) {
      outputChannel.appendLine(
        `FATAL Error during activation: ${e.message}\n${e.stack}`
      );
    }
  }
}

// --- 확장 기능 비활성화 함수 ---
export function deactivate() {
  try {
    outputChannel?.appendLine("Deactivating FindRuntimeErr extension.");
    if (outputChannel) {
      outputChannel.dispose();
    }
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
      debounceTimeout = null;
    }
    // diagnosticCollection, errorDecorationType, hoverProvider 는 context.subscriptions에 의해 자동 dispose
    console.log("FindRuntimeErr extension resources disposed.");
  } catch (e: any) {
    console.error("Error during extension deactivation:", e);
  }
}
