// src/extension.ts
import * as vscode from "vscode";
import { spawn, SpawnOptionsWithoutStdio, execSync, ChildProcess } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { WebviewManager } from './webviewManager';

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
  filePath?: string;
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

// 분석 결과 저장용 전역 변수
let realtimeAnalysisResults: Map<string, ErrorInfo[]> = new Map();
let preciseAnalysisResults: Map<string, ErrorInfo[]> = new Map();
let dynamicAnalysisResults: Map<string, any> = new Map(); // 동적분석 결과 저장

// 분석 결과 저장 함수들
export function saveRealtimeAnalysisResult(documentUri: string, errors: ErrorInfo[]): void {
  realtimeAnalysisResults.set(documentUri, errors);
}

export function savePreciseAnalysisResult(documentUri: string, errors: ErrorInfo[]): void {
  preciseAnalysisResults.set(documentUri, errors);
}

export function saveDynamicAnalysisResult(documentUri: string, result: any): void {
  dynamicAnalysisResults.set(documentUri, result);
}

export function getRealtimeAnalysisResults(): ErrorInfo[] {
  const allErrors: ErrorInfo[] = [];
  realtimeAnalysisResults.forEach(errors => {
    allErrors.push(...errors);
  });
  return allErrors;
}

export function getPreciseAnalysisResults(): ErrorInfo[] {
  const allErrors: ErrorInfo[] = [];
  preciseAnalysisResults.forEach(errors => {
    allErrors.push(...errors);
  });
  return allErrors;
}

export function getDynamicAnalysisResults(): any[] {
  const allResults: any[] = [];
  dynamicAnalysisResults.forEach(result => {
    allResults.push(result);
  });
  return allResults;
}

// --- 확장 기능 활성화 함수 ---
export function activate(context: vscode.ExtensionContext) {
  try {
    outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
    diagnosticCollection =
      vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);

    // 상태 표시줄에 버튼 추가
    const staticAnalysisButton = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    staticAnalysisButton.text = "$(search) 정적분석";
    staticAnalysisButton.tooltip = "정적 분석 실행";
    staticAnalysisButton.command = "findRuntimeErr.staticAnalysis";
    staticAnalysisButton.show();

    const dynamicAnalysisButton = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      99
    );
    dynamicAnalysisButton.text = "$(play) 동적분석";
    dynamicAnalysisButton.tooltip = "동적 분석 실행";
    dynamicAnalysisButton.command = "findRuntimeErr.dynamicAnalysis";
    dynamicAnalysisButton.show();

    // 컨텍스트에 추가
    context.subscriptions.push(staticAnalysisButton);
    context.subscriptions.push(dynamicAnalysisButton);

    // 명령어 등록
    const staticAnalysisCommand = vscode.commands.registerCommand(
      "findRuntimeErr.staticAnalysis",
      () => {
        // 정적분석 웹뷰 패널 열기
        const webviewManager = WebviewManager.getInstance();
        webviewManager.createStaticAnalysisPanel(context);
      }
    );

    const dynamicAnalysisCommand = vscode.commands.registerCommand(
      "findRuntimeErr.dynamicAnalysis",
      () => {
        // 동적분석 웹뷰 패널 열기
        const webviewManager = WebviewManager.getInstance();
        webviewManager.createDynamicAnalysisPanel(context);
      }
    );

    context.subscriptions.push(staticAnalysisCommand);
    context.subscriptions.push(dynamicAnalysisCommand);

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
      const requiredPackages = ["parso", "astroid", "networkx", "astor", "google-genai"];
      const missingPackages = requiredPackages.filter((pkg) => {
        try {
          // google-genai는 import 테스트도 추가로 수행
          if (pkg === "google-genai") {
            // 먼저 pip show로 확인
            execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
              stdio: "pipe",
            });
            
            // 추가로 import 테스트 수행
            try {
              execSync(`"${pythonExecutable}" -c "from google import genai; print('google-genai import successful')"`, {
                stdio: "pipe",
              });
            } catch (importError) {
              console.warn("google-genai import test failed:", importError);
              return true; // import 실패 시 누락된 것으로 간주
            }
            return false;
          } else {
            execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
              stdio: "pipe",
            });
            return false;
          }
        } catch {
          return true;
        }
      });
      return { missing: missingPackages };
    }

    async function installMissingPackages(pythonExecutable: string, missingPackages: string[]): Promise<boolean> {
      try {
        // 각 패키지를 개별적으로 설치하여 더 안정적으로 처리
        for (const pkg of missingPackages) {
          try {
            let installCommand: string;
            
            // google-genai 패키지는 특별한 처리가 필요할 수 있음
            if (pkg === "google-genai") {
              installCommand = `"${pythonExecutable}" -m pip install "google-genai>=0.3.0"`;
            } else {
              installCommand = `"${pythonExecutable}" -m pip install "${pkg}"`;
            }
            
            execSync(installCommand, { stdio: "pipe" });
            console.log(`Successfully installed ${pkg}`);
          } catch (error) {
            console.error(`Failed to install ${pkg}:`, error);
            
            // google-genai 설치 실패 시 대안 시도
            if (pkg === "google-genai") {
              try {
                console.log("Trying alternative installation for google-genai...");
                const altCommand = `"${pythonExecutable}" -m pip install --upgrade google-genai`;
                execSync(altCommand, { stdio: "pipe" });
                console.log("Successfully installed google-genai with alternative method");
              } catch (altError) {
                console.error("Alternative installation also failed:", altError);
              }
            }
            // 개별 패키지 설치 실패 시에도 계속 진행
          }
        }
        
        // 설치 후 다시 확인하여 실제로 설치된 패키지들 확인
        const recheckResult = checkPythonPackages(pythonExecutable);
        const stillMissing = recheckResult.missing.filter(pkg => missingPackages.includes(pkg));
        
        if (stillMissing.length > 0) {
          console.warn(`Still missing packages after installation: ${stillMissing.join(", ")}`);
          return false;
        }
        
        return true;
      } catch (error) {
        console.error("Failed to install packages:", error);
        return false;
      }
    }

    async function promptInstallPackages(pythonExecutable: string, missingPackages: string[]): Promise<boolean> {
      const message = `필요한 Python 패키지가 설치되지 않았습니다: ${missingPackages.join(", ")}`;
      const install = "자동 설치";
      const manual = "수동 설치";
      const cancel = "취소";
      
      const choice = await vscode.window.showWarningMessage(
        message,
        install,
        manual,
        cancel
      );
      
      if (choice === install) {
        const progressOptions = {
          location: vscode.ProgressLocation.Notification,
          title: "Python 패키지 설치 중...",
          cancellable: false
        };
        
        return await vscode.window.withProgress(progressOptions, async (progress) => {
          progress.report({ message: "패키지를 설치하는 중..." });
          
          const success = await installMissingPackages(pythonExecutable, missingPackages);
          
          if (success) {
            vscode.window.showInformationMessage("모든 패키지 설치가 완료되었습니다.");
            checkedPackages = false; // 재확인을 위해 리셋
            return true;
          } else {
            // 설치에 실패한 패키지들 확인
            const recheckResult = checkPythonPackages(pythonExecutable);
            const stillMissing = recheckResult.missing.filter(pkg => missingPackages.includes(pkg));
            
            if (stillMissing.length > 0) {
              vscode.window.showErrorMessage(
                `일부 패키지 설치에 실패했습니다: ${stillMissing.join(", ")}\n수동으로 설치해주세요.`
              );
            } else {
              vscode.window.showInformationMessage("패키지 설치가 완료되었습니다.");
              checkedPackages = false;
              return true;
            }
            return false;
          }
        });
      } else if (choice === manual) {
        const terminal = vscode.window.createTerminal("Package Installation");
        
        // google-genai가 포함된 경우 특별한 안내 제공
        if (missingPackages.includes("google-genai")) {
          terminal.sendText(`# Google Generative AI 패키지 설치`);
          terminal.sendText(`# 만약 설치에 문제가 있다면 다음 명령어를 시도해보세요:`);
          terminal.sendText(`# ${pythonExecutable} -m pip install --upgrade google-genai`);
          terminal.sendText(``);
        }
        
        terminal.sendText(`${pythonExecutable} -m pip install ${missingPackages.join(" ")}`);
        terminal.show();
        
        if (missingPackages.includes("google-genai")) {
          vscode.window.showInformationMessage(
            "터미널에서 패키지를 설치한 후 다시 시도해주세요.\n" +
            "google-genai 설치에 문제가 있다면 --upgrade 옵션을 사용해보세요."
          );
        } else {
          vscode.window.showInformationMessage("터미널에서 패키지를 설치한 후 다시 시도해주세요.");
        }
        return false;
      }
      
      return false;
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
      
      try {
        if (!checkedPackages) {
          const checkResult = checkPythonPackages(pythonExecutable);
          if (checkResult.missing.length > 0) {
            // 패키지 설치 옵션 제공
            const installSuccess = await promptInstallPackages(pythonExecutable, checkResult.missing);
            if (!installSuccess) {
              return {
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
              };
            }
            // 패키지 설치 후 다시 확인
            const recheckResult = checkPythonPackages(pythonExecutable);
            if (recheckResult.missing.length > 0) {
              return {
                errors: [
                  {
                    message: `Still missing packages after installation: ${recheckResult.missing.join(
                      ", "
                    )}. Please install them manually.`,
                    line: 1,
                    column: 0,
                    errorType: "MissingDependencyError",
                  },
                ],
                call_graph: null,
              };
            }
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

        return new Promise((resolve) => {
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
        });
      } catch (e: any) {
        return {
          errors: [
            {
              message: `Error setting up analysis: ${e.message}`,
              line: 1,
              column: 0,
              errorType: "SetupError",
            },
          ],
          call_graph: null,
        };
      }
    }

    async function runDynamicAnalysisProcess(
      code: string,
      documentUri?: vscode.Uri
    ): Promise<AnalysisResult> {
      let pythonExecutable: string;
      try {
        pythonExecutable = await getSelectedPythonPath(documentUri);
      } catch (e: any) {
        return {
          errors: [
            {
              message: `Failed to determine Python path: ${e.message}`,
              line: 1,
              column: 0,
              errorType: "PythonPathError",
            },
          ],
          call_graph: null,
        };
      }
      // Check packages
      const pkgCheck = checkPythonPackages(pythonExecutable);
      if (pkgCheck.missing.length > 0) {
        // 패키지 설치 옵션 제공
        const installSuccess = await promptInstallPackages(pythonExecutable, pkgCheck.missing);
        if (!installSuccess) {
          return {
            errors: [
              {
                message: `Missing packages: ${pkgCheck.missing.join(
                  ", "
                )}. Please install in ${pythonExecutable}.`,
                line: 1,
                column: 0,
                errorType: "MissingDependencyError",
              },
            ],
            call_graph: null,
          };
        }
        // 패키지 설치 후 다시 확인
        const recheckResult = checkPythonPackages(pythonExecutable);
        if (recheckResult.missing.length > 0) {
          return {
            errors: [
              {
                message: `Still missing packages after installation: ${recheckResult.missing.join(
                  ", "
                )}. Please install them manually.`,
                line: 1,
                column: 0,
                errorType: "MissingDependencyError",
              },
            ],
            call_graph: null,
          };
        }
      }

      const extensionRootPath = context.extensionPath;
      const scriptDir = path.join(extensionRootPath, "scripts");
      const scriptPath = path.join(scriptDir, "dynamic_analyze.py");
      if (!fs.existsSync(scriptPath)) {
        return {
          errors: [
            {
              message: `dynamic_analyze.py not found at ${scriptPath}`,
              line: 1,
              column: 0,
              errorType: "ScriptNotFoundError",
            },
          ],
          call_graph: null,
        };
      }

      return new Promise((resolve) => {
        const spawnOpts: SpawnOptionsWithoutStdio = { cwd: scriptDir };
        outputChannel.appendLine(
          `[runDynamicAnalysisProcess] Spawning: "${pythonExecutable}" "${scriptPath}"`
        );
        dynamicProcess = spawn(pythonExecutable, [scriptPath], spawnOpts);
        const proc = dynamicProcess;
        let stdoutData = "";
        let stderrData = "";
        proc.stdin?.write(code);
        proc.stdin?.end();
        proc.stdout?.on("data", (data) => {
          stdoutData += data;
        });
        proc.stderr?.on("data", (data) => {
          stderrData += data;
          outputChannel.appendLine(`[runDynamicAnalysisProcess] STDERR: ${data}`);
        });
        proc.on("close", (code, signal) => {
          // If process was killed (code === null), treat as user abort and return no errors
          if (code === null) {
            outputChannel.appendLine(`[runDynamicAnalysisProcess] Process killed by user (signal: ${signal}). Aborting dynamic analysis.`);
            resolve({ errors: [], call_graph: null });
            dynamicProcess = null;
            return;
          }
          outputChannel.appendLine(
            `[runDynamicAnalysisProcess] Process exited with code ${code}`
          );
          outputChannel.appendLine(
            `[runDynamicAnalysisProcess] RAW STDOUT: ${stdoutData}`
          );
          if (code !== 0) {
            resolve({
              errors: [
                {
                  message: `Dynamic analysis failed (Exit ${code}): ${stderrData.trim()}`,
                  line: 1,
                  column: 0,
                  errorType: "DynamicScriptError",
                },
              ],
              call_graph: null,
            });
            return;
          }
          try {
            const result: AnalysisResult = JSON.parse(stdoutData);
            resolve(result);
          } catch (e: any) {
            resolve({
              errors: [
                {
                  message: `Error parsing dynamic analysis result: ${e.message}`,
                  line: 1,
                  column: 0,
                  errorType: "JSONParseError",
                },
              ],
              call_graph: null,
            });
          }
          dynamicProcess = null;
        });
        proc.on("error", (err) => {
          resolve({
            errors: [
              {
                message: `Failed to start dynamic analysis process: ${err.message}`,
                line: 1,
                column: 0,
                errorType: "SpawnError",
              },
            ],
            call_graph: null,
          });
          dynamicProcess = null;
        });
      });
    }

    function handleAnalysisResult(
      documentUri: vscode.Uri,
      config: ExtensionConfig,
      result: AnalysisResult,
      mode: "realtime" | "static" = "realtime"
    ) {
      if (!result || !Array.isArray(result.errors)) return;
      const filteredErrors = result.errors.filter(
        (err) => !config.ignoredErrorTypes.includes(err.errorType.toLowerCase())
      );
      
      // 분석 결과 저장
      if (mode === "realtime") {
        // 파일 경로 정보 추가
        const errorsWithPath = filteredErrors.map(error => ({
          ...error,
          filePath: documentUri.fsPath
        }));
        saveRealtimeAnalysisResult(documentUri.toString(), errorsWithPath);
        // 웹뷰 자동 갱신
        const webviewManager = WebviewManager.getInstance();
        webviewManager.updateRealtimeErrorsInWebview();
      } else if (mode === "static") {
        // 파일 경로 정보 추가
        const errorsWithPath = filteredErrors.map(error => ({
          ...error,
          filePath: documentUri.fsPath
        }));
        savePreciseAnalysisResult(documentUri.toString(), errorsWithPath);
      }
      
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
          .then((result) => handleAnalysisResult(document.uri, config, result, "realtime"))
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
                handleAnalysisResult(editor.document.uri, config, result, "static");
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
          const editor = vscode.window.activeTextEditor;
          if (editor && editor.document.languageId === "python") {
            outputChannel.appendLine("[Command] findRuntimeErr.runDynamicAnalysis executed.");
            const config = getConfiguration();
            clearPreviousAnalysis(editor.document.uri);

            try {
              const result = await runDynamicAnalysisProcess(editor.document.getText(), editor.document.uri);
              
              handleAnalysisResult(editor.document.uri, config, result);
              
              // 동적분석 결과 저장
              saveDynamicAnalysisResult(editor.document.uri.toString(), result);
              
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
              
              return result; // Promise 결과로 반환
            } catch (error: any) {
              outputChannel.appendLine(`[Command Error] Dynamic analysis failed: ${error.message}`);
              vscode.window.showErrorMessage(
                `FindRuntimeErr: Dynamic analysis failed. ${error.message}`
              );
              throw error; // 오류를 다시 던져서 웹뷰에서 감지할 수 있도록 함
            }
          } else {
            const errorMessage = "FindRuntimeErr: Please open a Python file to run dynamic analysis.";
            vscode.window.showWarningMessage(errorMessage);
            throw new Error(errorMessage);
          }
        }
      )
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