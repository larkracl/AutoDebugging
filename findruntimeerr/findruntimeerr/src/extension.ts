// src/extension.ts
import * as vscode from "vscode";
import { spawn } from "child_process";
import * as path from "path";

const outputChannel = vscode.window.createOutputChannel("My Extension");

interface ExtensionConfig {
  enable: boolean;
  severityLevel: vscode.DiagnosticSeverity;
  enableDynamicAnalysis: boolean;
  ignoredErrorTypes: string[];
}

interface ErrorInfo {
  message: string;
  line: number;
  column: number;
  errorType: string;
}

export function activate(context: vscode.ExtensionContext) {
  outputChannel.appendLine("확장 프로그램이 활성화되었습니다.");

  const diagnosticCollection =
    vscode.languages.createDiagnosticCollection("findRuntimeErr");
  context.subscriptions.push(diagnosticCollection);

  // 초록색 밑줄 Decoration Type 생성
  const errorDecorationType = vscode.window.createTextEditorDecorationType({
    textDecoration: "underline wavy green", // 초록색 물결 밑줄
  });

  function getConfiguration(): ExtensionConfig {
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
    }

    // 로그: 설정을 가져온 결과 출력
    outputChannel.appendLine(`Configuration loaded: 
      enable=${config.get<boolean>("enable", true)}, 
      severityLevel=${severityLevel}, 
      enableDynamicAnalysis=${config.get<boolean>("enableDynamicAnalysis", false)},
      ignoredErrorTypes=${config.get<string[]>("ignoredErrorTypes", []).join(", ")}`);

    return {
      enable: config.get<boolean>("enable", true),
      severityLevel: diagnosticSeverity,
      enableDynamicAnalysis: config.get<boolean>("enableDynamicAnalysis", false),
      ignoredErrorTypes: config.get<string[]>("ignoredErrorTypes", []),
    };
  }

  function analyzeCode(
    code: string,
    documentUri: vscode.Uri,
    mode: "simple" | "detailed" = "simple",
    showStartMessage: boolean = false
  ) {
    outputChannel.appendLine(`[analyzeCode] Start analyzing code in ${mode} mode. Document URI: ${documentUri.toString()}`);
    
    diagnosticCollection.clear();
    const config = getConfiguration();
    if (!config.enable) {
      outputChannel.appendLine("[analyzeCode] Analysis is disabled by user configuration.");
      return;
    }

    // 운영체제에 따른 전용 Python 인터프리터 경로 설정
    const pythonExecutable =
      process.platform === "win32"
        ? path.join(context.extensionPath, ".venv_extension", "Scripts", "python.exe")
        : path.join(context.extensionPath, ".venv_extension", "bin", "python");

    // 분석 스크립트 경로 설정
    const pythonScriptPath = path.join(__dirname, "..", "scripts", "analyze.py");

    // 로그: Python 실행 파일, 스크립트 경로
    outputChannel.appendLine(`[analyzeCode] Using Python executable: ${pythonExecutable}`);
    outputChannel.appendLine(`[analyzeCode] Python script path: ${pythonScriptPath}`);

    // Python child process 생성
    const pythonProcess = spawn(pythonExecutable, [pythonScriptPath, mode]);

    let stdoutData = "";
    let stderrData = "";

    if (showStartMessage) {
      vscode.window.showInformationMessage("FindRuntimeErr: 검색 시작");
      outputChannel.appendLine("[analyzeCode] Showing progress notification to user.");

      vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "FindRuntimeErr: 탐지 중...",
          cancellable: false,
        },
        (progress) => {
          return new Promise<void>((resolve) => {
            outputChannel.appendLine("[analyzeCode] Writing code to Python process (withProgress).");
            pythonProcess.stdin.write(code);
            pythonProcess.stdin.end();

            pythonProcess.stdout.on("data", (data) => {
              outputChannel.appendLine("[analyzeCode] Received data from Python process stdout.");
              stdoutData += data;
            });

            pythonProcess.stderr.on("data", (data) => {
              outputChannel.appendLine("[analyzeCode] Received data from Python process stderr.");
              stderrData += data;
            });

            pythonProcess.on("close", (closeCode) => {
              outputChannel.appendLine(`[analyzeCode] Python process closed with code: ${closeCode}`);
              if (closeCode !== 0) {
                console.error(`Python script exited with code ${closeCode}`);
                console.error(stderrData);
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: Error analyzing code. See output for details. ${stderrData}`
                );
                outputChannel.appendLine(`[analyzeCode] Analysis failed: ${stderrData}`);

                const editor = vscode.window.activeTextEditor;
                if (editor) {
                  const fullRange = new vscode.Range(
                    0,
                    0,
                    editor.document.lineCount,
                    0
                  );
                  editor.setDecorations(errorDecorationType, [fullRange]);
                }
                resolve();
                return;
              }

              try {
                outputChannel.appendLine("[analyzeCode] Parsing analysis result (JSON).");
                const errors: ErrorInfo[] = JSON.parse(stdoutData);
                const diagnostics: vscode.Diagnostic[] = [];
                const decorationRanges: vscode.Range[] = [];

                errors.forEach((error) => {
                  if (!config.ignoredErrorTypes.includes(error.errorType)) {
                    const range = new vscode.Range(
                      error.line - 1,
                      error.column,
                      error.line - 1,
                      error.column + 1
                    );
                    const message = `${error.message} : ${error.errorType} : Line ${error.line}, Column ${error.column} : "AutoDebugging"`;
                    const diagnostic = new vscode.Diagnostic(
                      range,
                      message,
                      config.severityLevel
                    );
                    diagnostic.code = error.errorType;
                    diagnostics.push(diagnostic);
                    decorationRanges.push(range);
                  }
                });

                outputChannel.appendLine(`[analyzeCode] Total errors detected: ${diagnostics.length}`);
                diagnosticCollection.set(documentUri, diagnostics);

                const editor = vscode.window.activeTextEditor;
                if (
                  editor &&
                  editor.document.uri.toString() === documentUri.toString()
                ) {
                  outputChannel.appendLine(`[analyzeCode] Setting wavy underline decorations for ${decorationRanges.length} ranges.`);
                  editor.setDecorations(errorDecorationType, decorationRanges);
                }
              } catch (parseError) {
                console.error("Error parsing Python script output:", parseError);
                console.error("Raw output:", stdoutData);
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: Error parsing analysis results. See output for details. ${parseError}`
                );
                outputChannel.appendLine(`[analyzeCode] JSON parse error: ${parseError}`);

                const editor = vscode.window.activeTextEditor;
                if (editor) {
                  const fullRange = new vscode.Range(
                    0,
                    0,
                    editor.document.lineCount,
                    0
                  );
                  editor.setDecorations(errorDecorationType, [fullRange]);
                }
              } finally {
                resolve();
              }
            });
          });
        }
      );
    } else {
      outputChannel.appendLine("[analyzeCode] Writing code to Python process (no progress notification).");
      pythonProcess.stdin.write(code);
      pythonProcess.stdin.end();

      pythonProcess.stdout.on("data", (data) => {
        outputChannel.appendLine("[analyzeCode] Received data from Python process stdout.");
        stdoutData += data;
      });

      pythonProcess.stderr.on("data", (data) => {
        outputChannel.appendLine("[analyzeCode] Received data from Python process stderr.");
        stderrData += data;
      });

      pythonProcess.on("close", (closeCode) => {
        outputChannel.appendLine(`[analyzeCode] Python process closed with code: ${closeCode}`);
        if (closeCode !== 0) {
          console.error(`Python script exited with code ${closeCode}`);
          console.error(stderrData);
          vscode.window.showErrorMessage(
            `FindRuntimeErr: Error analyzing code. See output for details. ${stderrData}`
          );
          outputChannel.appendLine(`[analyzeCode] Analysis failed: ${stderrData}`);

          const editor = vscode.window.activeTextEditor;
          if (editor) {
            const fullRange = new vscode.Range(
              0,
              0,
              editor.document.lineCount,
              0
            );
            editor.setDecorations(errorDecorationType, [fullRange]);
          }
          return;
        }

        try {
          outputChannel.appendLine("[analyzeCode] Parsing analysis result (JSON).");
          const errors: ErrorInfo[] = JSON.parse(stdoutData);
          const diagnostics: vscode.Diagnostic[] = [];
          const decorationRanges: vscode.Range[] = [];

          errors.forEach((error) => {
            if (!config.ignoredErrorTypes.includes(error.errorType)) {
              const range = new vscode.Range(
                error.line - 1,
                error.column,
                error.line - 1,
                error.column + 1
              );
              const message = `${error.message} : ${error.errorType} : Line ${error.line}, Column ${error.column} : "AutoDebugging"`;
              const diagnostic = new vscode.Diagnostic(
                range,
                message,
                config.severityLevel
              );
              diagnostic.code = error.errorType;
              diagnostics.push(diagnostic);
              decorationRanges.push(range);
            }
          });

          outputChannel.appendLine(`[analyzeCode] Total errors detected: ${diagnostics.length}`);
          diagnosticCollection.set(documentUri, diagnostics);

          const editor = vscode.window.activeTextEditor;
          if (
            editor &&
            editor.document.uri.toString() === documentUri.toString()
          ) {
            outputChannel.appendLine(`[analyzeCode] Setting wavy underline decorations for ${decorationRanges.length} ranges.`);
            editor.setDecorations(errorDecorationType, decorationRanges);
          }
        } catch (parseError) {
          console.error("Error parsing Python script output:", parseError);
          console.error("Raw output:", stdoutData);
          vscode.window.showErrorMessage(
            `FindRuntimeErr: Error parsing analysis results. See output for details. ${parseError}`
          );
          outputChannel.appendLine(`[analyzeCode] JSON parse error: ${parseError}`);

          const editor = vscode.window.activeTextEditor;
          if (editor) {
            const fullRange = new vscode.Range(
              0,
              0,
              editor.document.lineCount,
              0
            );
            editor.setDecorations(errorDecorationType, [fullRange]);
          }
        }
      });
    }
  }

  vscode.workspace.onDidChangeTextDocument((event) => {
    if (event.document.languageId === "python") {
      outputChannel.appendLine("[onDidChangeTextDocument] Python document changed, triggering analysis.");
      analyzeCode(event.document.getText(), event.document.uri);
    }
  });

  vscode.workspace.onDidOpenTextDocument((document) => {
    if (document.languageId === "python") {
      outputChannel.appendLine("[onDidOpenTextDocument] Python document opened, triggering analysis.");
      analyzeCode(document.getText(), document.uri);
    }
  });

  vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration("findRuntimeErr")) {
      outputChannel.appendLine("[onDidChangeConfiguration] findRuntimeErr configuration changed.");
      if (
        vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.languageId === "python"
      ) {
        outputChannel.appendLine("[onDidChangeConfiguration] Re-analyzing active Python file.");
        analyzeCode(
          vscode.window.activeTextEditor.document.getText(),
          vscode.window.activeTextEditor.document.uri
        );
      }
    }
  });

  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        outputChannel.appendLine("[command] findRuntimeErr.analyzeCurrentFile triggered.");
        analyzeCode(editor.document.getText(), editor.document.uri, "detailed", true);
      } else {
        vscode.window.showWarningMessage(
          "FindRuntimeErr: Please open a Python file to analyze."
        );
        outputChannel.appendLine("[command] analyzeCurrentFile: No Python file open.");
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        vscode.window.showInformationMessage(
          "FindRuntimeErr: Dynamic analysis is not yet implemented."
        );
        outputChannel.appendLine("[command] runDynamicAnalysis: Not yet implemented.");
      } else {
        vscode.window.showWarningMessage(
          "FindRuntimeErr: Please open a Python file to run dynamic analysis."
        );
        outputChannel.appendLine("[command] runDynamicAnalysis: No Python file open.");
      }
    })
  );

  if (
    vscode.window.activeTextEditor &&
    vscode.window.activeTextEditor.document.languageId === "python"
  ) {
    outputChannel.appendLine("[activate] Active editor is Python, starting initial analysis.");
    analyzeCode(
      vscode.window.activeTextEditor.document.getText(),
      vscode.window.activeTextEditor.document.uri
    );
  }
}

export function deactivate() {
  outputChannel.appendLine("확장 프로그램이 비활성화되었습니다.");
}
