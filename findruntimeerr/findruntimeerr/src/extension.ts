// src/extension.ts
import * as vscode from "vscode";
import { spawn } from "child_process";
import * as path from "path";

const outputChannel = vscode.window.createOutputChannel("FindRuntimeErr"); // 출력 채널

interface ExtensionConfig {
  enable: boolean;
  severityLevel: vscode.DiagnosticSeverity;
  enableDynamicAnalysis: boolean; // (현재 미구현)
  ignoredErrorTypes: string[];
}

interface ErrorInfo {
  message: string;
  line: number;
  column: number;
  errorType: string;
}

export function activate(context: vscode.ExtensionContext) {
  outputChannel.appendLine("FindRuntimeErr 확장 프로그램이 활성화되었습니다.");

  const diagnosticCollection =
    vscode.languages.createDiagnosticCollection("findRuntimeErr");
  context.subscriptions.push(diagnosticCollection);

  const errorDecorationType = vscode.window.createTextEditorDecorationType({
    textDecoration: "underline wavy green",
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

    return {
      enable: config.get<boolean>("enable", true),
      severityLevel: diagnosticSeverity,
      enableDynamicAnalysis: config.get<boolean>(
        "enableDynamicAnalysis",
        false
      ),
      ignoredErrorTypes: config.get<string[]>("ignoredErrorTypes", []),
    };
  }

  function analyzeCode(
    code: string,
    documentUri: vscode.Uri,
    mode: "realtime" | "static" = "realtime",
    showStartMessage: boolean = false
  ) {
    diagnosticCollection.clear();
    const config = getConfiguration();
    if (!config.enable) {
      return;
    }

    const pythonProcess = spawn("python3", [
      path.join(context.extensionPath, "scripts", "main.py"),
      mode,
    ]);

    let stdoutData = "";
    let stderrData = "";

    if (showStartMessage) {
      vscode.window.showInformationMessage("FindRuntimeErr: 검색 시작");
      vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "FindRuntimeErr: 탐지 중...",
          cancellable: false,
        },
        (progress) => {
          return new Promise<void>((resolve) => {
            pythonProcess.stdin.write(code);
            pythonProcess.stdin.end();

            pythonProcess.stdout.on("data", (data) => {
              stdoutData += data;
            });

            pythonProcess.stderr.on("data", (data) => {
              stderrData += data;
            });

            pythonProcess.on("close", (code) => {
              if (code !== 0) {
                console.error(`Python script exited with code ${code}`);
                console.error(stderrData);
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: Error analyzing code. See output for details. ${stderrData}`
                );
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
                resolve(); // 오류 발생 시에도 Promise를 resolve하여 "탐지 중..." 메시지 닫기
                return;
              }

              try {
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

                diagnosticCollection.set(documentUri, diagnostics);

                const editor = vscode.window.activeTextEditor;
                if (
                  editor &&
                  editor.document.uri.toString() === documentUri.toString()
                ) {
                  editor.setDecorations(errorDecorationType, decorationRanges);
                }
              } catch (parseError) {
                console.error(
                  "Error parsing Python script output:",
                  parseError
                );
                console.error("Raw output:", stdoutData);
                vscode.window.showErrorMessage(
                  `FindRuntimeErr: Error parsing analysis results. See output for details. ${parseError}`
                );

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
                vscode.window
                  .showInformationMessage("FindRuntimeErr: 탐지 종료")
                  .then(() => {});
                resolve(); // 오류 발생 여부와 관계없이 Promise 완료 (progress 종료)
              }
            });
          });
        }
      );
    } else {
      // 실시간 분석 (showStartMessage == false)
      pythonProcess.stdin.write(code);
      pythonProcess.stdin.end();

      pythonProcess.stdout.on("data", (data) => {
        stdoutData += data;
      });

      pythonProcess.stderr.on("data", (data) => {
        stderrData += data;
      });

      pythonProcess.on("close", (code) => {
        if (code !== 0) {
          console.error(`Python script exited with code ${code}`);
          console.error(stderrData);
          vscode.window.showErrorMessage(
            `FindRuntimeErr: Error analyzing code. See output for details. ${stderrData}`
          );
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

          diagnosticCollection.set(documentUri, diagnostics);

          const editor = vscode.window.activeTextEditor;
          if (
            editor &&
            editor.document.uri.toString() === documentUri.toString()
          ) {
            editor.setDecorations(errorDecorationType, decorationRanges);
          }
        } catch (parseError) {
          console.error("Error parsing Python script output:", parseError);
          console.error("Raw output:", stdoutData);
          vscode.window.showErrorMessage(
            `FindRuntimeErr: Error parsing analysis results. See output for details. ${parseError}`
          );

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
      analyzeCode(event.document.getText(), event.document.uri);
    }
  });

  vscode.workspace.onDidOpenTextDocument((document) => {
    if (document.languageId === "python") {
      analyzeCode(document.getText(), document.uri);
    }
  });

  vscode.workspace.onDidChangeConfiguration((e) => {
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
  });

  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        analyzeCode(
          editor.document.getText(),
          editor.document.uri,
          "static",
          true
        ); // 'static' 모드
      } else {
        vscode.window.showWarningMessage(
          "FindRuntimeErr: Please open a Python file to analyze."
        );
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        // TODO: 동적 분석 구현
        vscode.window.showInformationMessage(
          "FindRuntimeErr: Dynamic analysis is not yet implemented."
        );
      } else {
        vscode.window.showWarningMessage(
          "FindRuntimeErr: Please open a Python file to run dynamic analysis."
        );
      }
    })
  );

  // 초기 실행 (활성 Python 파일이 있으면 분석)
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

export function deactivate() {
  outputChannel.dispose(); // 출력 채널 해제
}
