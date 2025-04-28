// src/extension.ts
import * as vscode from "vscode";
import { spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

const outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");

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
  outputChannel.appendLine("FindRuntimeErr 확장 프로그램이 활성화되었습니다.");

  const diagnosticCollection =
    vscode.languages.createDiagnosticCollection("findRuntimeErr");
  context.subscriptions.push(diagnosticCollection);

  const errorDecorationType = vscode.window.createTextEditorDecorationType({
    textDecoration: "underline wavy green",
  });

  let debounceTimeout: NodeJS.Timeout | null = null;
  const debounceDelay = 500;

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
  }

  function runAnalysisProcess(
    code: string,
    mode: "realtime" | "static"
  ): Promise<AnalysisResult> {
    return new Promise((resolve, reject) => {
      const pythonExecutable = "python3";
      const mainScriptPath = path.join(
        context.extensionPath,
        "scripts",
        "main.py"
      );
      outputChannel.appendLine(
        `[runAnalysis] Spawning: ${pythonExecutable} ${mainScriptPath} ${mode}`
      );
      const pythonProcess = spawn(pythonExecutable, [mainScriptPath, mode]);

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
        outputChannel.appendLine(
          `[runAnalysis] Python process finished with code: ${closeCode} (${mode})`
        );
        if (closeCode !== 0) {
          let errorDetail = `Analysis script failed (Exit Code: ${closeCode}).`;
          if (stdoutData.trim()) {
            try {
              const errorResult = JSON.parse(stdoutData);
              if (errorResult?.errors?.[0]?.message) {
                errorDetail = errorResult.errors[0].message;
              }
            } catch {}
          }
          if (stderrData.trim()) {
            errorDetail += `\nStderr: ${stderrData.trim()}`;
          }
          reject(new Error(errorDetail)); // 오류 메시지와 함께 reject
          return;
        }
        try {
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
            reject(
              new Error(
                "Invalid analysis result format. 'errors' key is missing or not an array."
              )
            );
          }
        } catch (parseError: any) {
          reject(
            new Error(
              `Error parsing analysis results: ${parseError.message}. Raw data: ${stdoutData}`
            )
          );
        }
      });

      pythonProcess.on("error", (err) => {
        reject(new Error(`Failed to start analysis process: ${err.message}`));
      });
    });
  }

  async function analyzeCode(
    code: string,
    documentUri: vscode.Uri,
    mode: "realtime" | "static" = "realtime",
    showProgress: boolean = false
  ) {
    const config = getConfiguration();

    if (mode === "realtime") {
      if (!config.enable) {
        outputChannel.appendLine("[analyzeCode] Real-time analysis disabled.");
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

    clearPreviousAnalysis(documentUri); // 분석 시작 시 이전 결과 지우기

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
            const result = await runAnalysisProcess(code, mode);
            handleAnalysisResult(documentUri, config, result, mode);
            vscode.window.showInformationMessage(
              `FindRuntimeErr: 분석 완료. ${result.errors.length}개의 오류 발견.`
            );
            outputChannel.appendLine(
              `[analyzeCode] Analysis successful (${mode}). ${result.errors.length} errors found.`
            );
          } catch (error: any) {
            console.error("Analysis failed:", error);
            vscode.window.showErrorMessage(
              `FindRuntimeErr: 분석 실패. ${error.message}`
            );
            outputChannel.appendLine(
              `[analyzeCode] Analysis failed (${mode}): ${error.message}`
            );
          }
        }
      );
    } else {
      try {
        const result = await runAnalysisProcess(code, mode);
        handleAnalysisResult(documentUri, config, result, mode);
      } catch (error: any) {
        console.error("Real-time analysis failed:", error);
        outputChannel.appendLine(
          `[analyzeCode] Real-time analysis failed: ${error.message}`
        );
      }
    }
  }

  function handleAnalysisResult(
    documentUri: vscode.Uri,
    config: ExtensionConfig,
    result: AnalysisResult,
    mode: string
  ) {
    try {
      const errors: ErrorInfo[] = result.errors || [];
      outputChannel.appendLine(
        `[handleResult] Processing ${errors.length} errors.`
      );
      displayDiagnostics(documentUri, config, errors);

      const callGraphData = result.call_graph;
      if (callGraphData && mode === "static") {
        outputChannel.appendLine(`[handleResult] Call graph data received:`);
        outputChannel.appendLine(JSON.stringify(callGraphData, null, 2)); // Output 채널에 JSON 출력
        console.log("Call Graph Data:", callGraphData);
        // TODO: 그래프 데이터 활용 로직
      }
    } catch (error: any) {
      console.error("Error handling analysis result:", error);
      outputChannel.appendLine(
        `[handleResult] Error handling analysis result: ${error.message}`
      );
    }
  }

  function displayDiagnostics(
    documentUri: vscode.Uri,
    config: ExtensionConfig,
    errors: ErrorInfo[]
  ) {
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

      if (!config.ignoredErrorTypes.includes(error.errorType)) {
        const line = Math.max(0, error.line - 1);
        const column = Math.max(0, error.column);
        const range = new vscode.Range(line, column, line, column + 1);

        const message = `${error.message} : ${error.errorType} : Line ${error.line}, Column ${error.column} : "AutoDebugging"`;
        const diagnosticSeverity = config.severityLevel;
        const finalSeverity =
          error.errorType === "SyntaxError"
            ? vscode.DiagnosticSeverity.Error
            : diagnosticSeverity;

        const diagnostic = new vscode.Diagnostic(range, message, finalSeverity);
        diagnostic.code = error.errorType;
        diagnostics.push(diagnostic);

        // 밑줄 표시 조건: Error 또는 Warning
        if (
          finalSeverity === vscode.DiagnosticSeverity.Error ||
          finalSeverity === vscode.DiagnosticSeverity.Warning
        ) {
          decorationRanges.push(range);
        }
      }
    });

    diagnosticCollection.set(documentUri, diagnostics);

    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document.uri.toString() === documentUri.toString()) {
      outputChannel.appendLine(
        `[displayDiagnostics] Setting decorations for ${decorationRanges.length} ranges.`
      );
      editor.setDecorations(errorDecorationType, decorationRanges);
    }
  }

  function clearPreviousAnalysis(documentUri: vscode.Uri) {
    diagnosticCollection.delete(documentUri);
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document.uri.toString() === documentUri.toString()) {
      editor.setDecorations(errorDecorationType, []);
    }
  }

  // --- 이벤트 리스너 ---
  vscode.workspace.onDidChangeTextDocument((event) => {
    if (event.document.languageId === "python") {
      if (debounceTimeout) {
        clearTimeout(debounceTimeout);
      }
      debounceTimeout = setTimeout(() => {
        outputChannel.appendLine(
          "[onDidChangeTextDocument] Debounced analysis triggered."
        );
        analyzeCode(event.document.getText(), event.document.uri, "realtime");
        debounceTimeout = null;
      }, debounceDelay);
    }
  });

  vscode.workspace.onDidOpenTextDocument((document) => {
    if (document.languageId === "python") {
      outputChannel.appendLine(
        "[onDidOpenTextDocument] Python document opened, triggering analysis."
      );
      analyzeCode(document.getText(), document.uri, "realtime");
    }
  });

  vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration("findRuntimeErr")) {
      outputChannel.appendLine(
        "[onDidChangeConfiguration] Configuration changed."
      );
      if (
        vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.languageId === "python"
      ) {
        outputChannel.appendLine(
          "[onDidChangeConfiguration] Re-analyzing active Python file."
        );
        analyzeCode(
          vscode.window.activeTextEditor.document.getText(),
          vscode.window.activeTextEditor.document.uri
        );
      }
    }
  });

  // --- 명령어 등록 ---
  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        outputChannel.appendLine(
          "[Command] findRuntimeErr.analyzeCurrentFile executed."
        );
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
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", () => {
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
    })
  );

  // --- 초기 실행 ---
  if (
    vscode.window.activeTextEditor &&
    vscode.window.activeTextEditor.document.languageId === "python"
  ) {
    outputChannel.appendLine(
      "[Activate] Analyzing initially active Python file."
    );
    analyzeCode(
      vscode.window.activeTextEditor.document.getText(),
      vscode.window.activeTextEditor.document.uri
    );
  }
}

export function deactivate() {
  outputChannel.dispose();
}
