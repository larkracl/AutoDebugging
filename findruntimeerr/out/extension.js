"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
// src/extension.ts
const vscode = require("vscode");
const child_process_1 = require("child_process");
const path = require("path");
const outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
function activate(context) {
    outputChannel.appendLine("FindRuntimeErr 확장 프로그램이 활성화되었습니다.");
    const diagnosticCollection = vscode.languages.createDiagnosticCollection("findRuntimeErr");
    context.subscriptions.push(diagnosticCollection);
    const errorDecorationType = vscode.window.createTextEditorDecorationType({
        textDecoration: "underline wavy green",
    });
    let debounceTimeout = null;
    const debounceDelay = 500;
    function getConfiguration() {
        const config = vscode.workspace.getConfiguration("findRuntimeErr");
        const severityLevel = config.get("severityLevel", "error");
        let diagnosticSeverity;
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
            enable: config.get("enable", true),
            severityLevel: diagnosticSeverity,
            enableDynamicAnalysis: config.get("enableDynamicAnalysis", false),
            ignoredErrorTypes: config.get("ignoredErrorTypes", []),
            minAnalysisLength: config.get("minAnalysisLength", 50),
        };
    }
    function runAnalysisProcess(code, mode) {
        return new Promise((resolve, reject) => {
            const pythonExecutable = path.join(context.extensionPath, "venv", "bin", "python");
            const mainScriptPath = path.join(context.extensionPath, "scripts", "main.py");
            outputChannel.appendLine(`[runAnalysis] Spawning: ${pythonExecutable} ${mainScriptPath} ${mode}`);
            const pythonProcess = (0, child_process_1.spawn)(pythonExecutable, [mainScriptPath, mode]);
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
                outputChannel.appendLine(`[runAnalysis] Python process finished with code: ${closeCode} (${mode})`);
                if (closeCode !== 0) {
                    let errorDetail = `Analysis script failed (Exit Code: ${closeCode}).`;
                    if (stdoutData.trim()) {
                        try {
                            const errorResult = JSON.parse(stdoutData);
                            if (errorResult?.errors?.[0]?.message) {
                                errorDetail = errorResult.errors[0].message;
                            }
                        }
                        catch { }
                    }
                    if (stderrData.trim()) {
                        errorDetail += `\nStderr: ${stderrData.trim()}`;
                    }
                    reject(new Error(errorDetail)); // 오류 메시지와 함께 reject
                    return;
                }
                try {
                    outputChannel.appendLine(`[runAnalysis] Raw stdout (${mode}): ${stdoutData}`);
                    if (!stdoutData.trim()) {
                        resolve({ errors: [], call_graph: null });
                        return;
                    }
                    const result = JSON.parse(stdoutData);
                    if (result && Array.isArray(result.errors)) {
                        resolve(result);
                    }
                    else {
                        reject(new Error("Invalid analysis result format. 'errors' key is missing or not an array."));
                    }
                }
                catch (parseError) {
                    reject(new Error(`Error parsing analysis results: ${parseError.message}. Raw data: ${stdoutData}`));
                }
            });
            pythonProcess.on("error", (err) => {
                reject(new Error(`Failed to start analysis process: ${err.message}`));
            });
        });
    }
    function runDynamicAnalysisProcess(code) {
        return new Promise((resolve, reject) => {
            const pythonExecutable = path.join(context.extensionPath, "venv", "bin", "python");
            const scriptPath = path.join(context.extensionPath, "scripts", "dynamic_analyze.py");
            outputChannel.appendLine(`[runDynamicAnalysis] Spawning: ${pythonExecutable} ${scriptPath}`);
            const pythonProcess = (0, child_process_1.spawn)(pythonExecutable, [scriptPath]);
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
                    const result = JSON.parse(stdoutData);
                    resolve(result);
                }
                catch (error) {
                    reject(new Error(`Error parsing dynamic analysis result: ${error.message}`));
                }
            });
            pythonProcess.on("error", (err) => {
                reject(new Error(`Failed to start dynamic analysis: ${err.message}`));
            });
        });
    }
    async function analyzeCode(code, documentUri, mode = "realtime", showProgress = false) {
        const config = getConfiguration();
        if (mode === "realtime") {
            if (!config.enable) {
                outputChannel.appendLine("[analyzeCode] Real-time analysis disabled.");
                clearPreviousAnalysis(documentUri);
                return;
            }
            if (code.length < config.minAnalysisLength) {
                outputChannel.appendLine(`[analyzeCode] Code length (${code.length}) < minAnalysisLength (${config.minAnalysisLength}). Skipping real-time analysis.`);
                clearPreviousAnalysis(documentUri);
                return;
            }
        }
        clearPreviousAnalysis(documentUri); // 분석 시작 시 이전 결과 지우기
        if (showProgress) {
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: "FindRuntimeErr: 분석 실행 중...",
                cancellable: false,
            }, async (progress) => {
                try {
                    progress.report({ message: "정적 분석 수행 중..." });
                    const result = await runAnalysisProcess(code, mode);
                    handleAnalysisResult(documentUri, config, result, mode);
                    vscode.window.showInformationMessage(`FindRuntimeErr: 분석 완료. ${result.errors.length}개의 오류 발견.`);
                    outputChannel.appendLine(`[analyzeCode] Analysis successful (${mode}). ${result.errors.length} errors found.`);
                }
                catch (error) {
                    console.error("Analysis failed:", error);
                    vscode.window.showErrorMessage(`FindRuntimeErr: 분석 실패. ${error.message}`);
                    outputChannel.appendLine(`[analyzeCode] Analysis failed (${mode}): ${error.message}`);
                }
            });
        }
        else {
            try {
                const result = await runAnalysisProcess(code, mode);
                handleAnalysisResult(documentUri, config, result, mode);
            }
            catch (error) {
                console.error("Real-time analysis failed:", error);
                outputChannel.appendLine(`[analyzeCode] Real-time analysis failed: ${error.message}`);
            }
        }
    }
    function handleAnalysisResult(documentUri, config, result, mode) {
        try {
            const errors = result.errors || [];
            outputChannel.appendLine(`[handleResult] Processing ${errors.length} errors.`);
            displayDiagnostics(documentUri, config, errors);
            const callGraphData = result.call_graph;
            if (callGraphData && mode === "static") {
                outputChannel.appendLine(`[handleResult] Call graph data received:`);
                outputChannel.appendLine(JSON.stringify(callGraphData, null, 2)); // Output 채널에 JSON 출력
                console.log("Call Graph Data:", callGraphData);
                // TODO: 그래프 데이터 활용 로직
            }
        }
        catch (error) {
            console.error("Error handling analysis result:", error);
            outputChannel.appendLine(`[handleResult] Error handling analysis result: ${error.message}`);
        }
    }
    function displayDiagnostics(documentUri, config, errors) {
        outputChannel.appendLine(`[displayDiagnostics] Displaying ${errors.length} diagnostics.`);
        const diagnostics = [];
        const decorationRanges = [];
        errors.forEach((error) => {
            if (!error ||
                typeof error.message !== "string" ||
                typeof error.line !== "number" ||
                typeof error.column !== "number" ||
                typeof error.errorType !== "string") {
                outputChannel.appendLine(`[displayDiagnostics] Skipping invalid error object: ${JSON.stringify(error)}`);
                return;
            }
            if (!config.ignoredErrorTypes.includes(error.errorType)) {
                const line = Math.max(0, error.line - 1);
                const column = Math.max(0, error.column);
                const range = new vscode.Range(line, column, line, column + 1);
                const message = `${error.message} : ${error.errorType} : Line ${error.line}, Column ${error.column} : "AutoDebugging"`;
                const diagnosticSeverity = config.severityLevel;
                const finalSeverity = error.errorType === "SyntaxError"
                    ? vscode.DiagnosticSeverity.Error
                    : diagnosticSeverity;
                const diagnostic = new vscode.Diagnostic(range, message, finalSeverity);
                diagnostic.code = error.errorType;
                diagnostics.push(diagnostic);
                // 밑줄 표시 조건: Error 또는 Warning
                if (finalSeverity === vscode.DiagnosticSeverity.Error ||
                    finalSeverity === vscode.DiagnosticSeverity.Warning) {
                    decorationRanges.push(range);
                }
            }
        });
        diagnosticCollection.set(documentUri, diagnostics);
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.uri.toString() === documentUri.toString()) {
            outputChannel.appendLine(`[displayDiagnostics] Setting decorations for ${decorationRanges.length} ranges.`);
            editor.setDecorations(errorDecorationType, decorationRanges);
        }
    }
    function clearPreviousAnalysis(documentUri) {
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
                outputChannel.appendLine("[onDidChangeTextDocument] Debounced analysis triggered.");
                analyzeCode(event.document.getText(), event.document.uri, "realtime");
                debounceTimeout = null;
            }, debounceDelay);
        }
    });
    vscode.workspace.onDidOpenTextDocument((document) => {
        if (document.languageId === "python") {
            outputChannel.appendLine("[onDidOpenTextDocument] Python document opened, triggering analysis.");
            analyzeCode(document.getText(), document.uri, "realtime");
        }
    });
    vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("findRuntimeErr")) {
            outputChannel.appendLine("[onDidChangeConfiguration] Configuration changed.");
            if (vscode.window.activeTextEditor &&
                vscode.window.activeTextEditor.document.languageId === "python") {
                outputChannel.appendLine("[onDidChangeConfiguration] Re-analyzing active Python file.");
                analyzeCode(vscode.window.activeTextEditor.document.getText(), vscode.window.activeTextEditor.document.uri);
            }
        }
    });
    // --- 명령어 등록 ---
    context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", () => {
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.languageId === "python") {
            outputChannel.appendLine("[Command] findRuntimeErr.analyzeCurrentFile executed.");
            analyzeCode(editor.document.getText(), editor.document.uri, "static", true);
        }
        else {
            vscode.window.showWarningMessage("FindRuntimeErr: Please open a Python file to analyze.");
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", () => {
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.languageId === "python") {
            outputChannel.appendLine("[Command] findRuntimeErr.runDynamicAnalysis executed.");
            const config = getConfiguration();
            clearPreviousAnalysis(editor.document.uri);
            runDynamicAnalysisProcess(editor.document.getText())
                .then((result) => {
                handleAnalysisResult(editor.document.uri, config, result, "dynamic");
                vscode.window.showInformationMessage(`FindRuntimeErr: Dynamic analysis completed. ${result.errors.length} error(s) found.`);
            })
                .catch((error) => {
                outputChannel.appendLine(`[Command Error] Dynamic analysis failed: ${error.message}`);
                vscode.window.showErrorMessage(`FindRuntimeErr: Dynamic analysis failed. ${error.message}`);
            });
        }
        else {
            vscode.window.showWarningMessage("FindRuntimeErr: Please open a Python file to run dynamic analysis.");
        }
    }));
    // --- 초기 실행 ---
    if (vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.languageId === "python") {
        outputChannel.appendLine("[Activate] Analyzing initially active Python file.");
        analyzeCode(vscode.window.activeTextEditor.document.getText(), vscode.window.activeTextEditor.document.uri);
    }
}
function deactivate() {
    outputChannel.dispose();
}
//# sourceMappingURL=extension.js.map