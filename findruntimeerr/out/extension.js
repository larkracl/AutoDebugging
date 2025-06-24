"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getAnalysisResults = getAnalysisResults;
exports.getDynamicAnalysisResult = getDynamicAnalysisResult;
exports.activate = activate;
exports.deactivate = deactivate;
// src/extension.ts
const vscode = require("vscode");
const child_process_1 = require("child_process");
const path = require("path");
const fs = require("fs");
const webviewManager_1 = require("./webviewManager");
// --- 전역 변수 ---
let outputChannel;
let diagnosticCollection;
let lastUsedPythonExecutable = null;
let checkedPackages = false;
let debounceTimeout = null;
let dynamicProcess = null;
// --- 분석 결과 저장을 위한 전역 상태 ---
let realtimeAnalysisResults = new Map();
let preciseAnalysisResults = new Map();
let dynamicAnalysisResults = new Map();
// --- 외부 모듈(WebviewManager)에서 사용할 수 있도록 export ---
function getAnalysisResults(type, uri) {
    const results = type === "realtime" ? realtimeAnalysisResults : preciseAnalysisResults;
    const docUri = uri?.toString();
    if (docUri)
        return results.get(docUri) || [];
    return Array.from(results.values()).flat();
}
function getDynamicAnalysisResult(uri) {
    return dynamicAnalysisResults.get(uri.toString());
}
function activate(context) {
    try {
        outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
        diagnosticCollection =
            vscode.languages.createDiagnosticCollection("findRuntimeErr");
        context.subscriptions.push(diagnosticCollection);
        const webviewManager = webviewManager_1.WebviewManager.getInstance(context);
        // 상태 표시줄 버튼
        const staticAnalysisButton = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        staticAnalysisButton.text = "$(search) 정적분석";
        staticAnalysisButton.tooltip = "정적 분석 패널 열기";
        staticAnalysisButton.command = "findRuntimeErr.showStaticAnalysis";
        staticAnalysisButton.show();
        context.subscriptions.push(staticAnalysisButton);
        const dynamicAnalysisButton = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
        dynamicAnalysisButton.text = "$(play) 동적분석";
        dynamicAnalysisButton.tooltip = "동적 분석 패널 열기";
        dynamicAnalysisButton.command = "findRuntimeErr.showDynamicAnalysis";
        dynamicAnalysisButton.show();
        context.subscriptions.push(dynamicAnalysisButton);
        const debounceDelay = 500;
        function getConfiguration() {
            const config = vscode.workspace.getConfiguration("findRuntimeErr");
            const severityLevel = config.get("severityLevel", "error");
            let diagnosticSeverity;
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
                default:
                    diagnosticSeverity = vscode.DiagnosticSeverity.Error;
                    break;
            }
            return {
                enable: config.get("enable", true),
                severityLevel: diagnosticSeverity,
                ignoredErrorTypes: config
                    .get("ignoredErrorTypes", [])
                    .map((t) => t.toLowerCase()),
                pythonPath: config.get("pythonPath", null),
                enableInlayHints: config.get("enableInlayHints", true),
                minAnalysisLength: config.get("minAnalysisLength", 10),
            };
        }
        async function getSelectedPythonPath(resource) {
            const config = getConfiguration();
            if (config.pythonPath)
                return config.pythonPath;
            try {
                const pythonExtension = vscode.extensions.getExtension("ms-python.python");
                if (pythonExtension) {
                    if (!pythonExtension.isActive) {
                        await pythonExtension.activate();
                    }
                    const api = pythonExtension.exports;
                    const envPath = api?.environments?.getActiveEnvironmentPath(resource)?.path;
                    if (envPath) {
                        const environment = await api.environments.resolveEnvironment(envPath);
                        if (environment?.path)
                            return environment.path;
                    }
                }
            }
            catch (err) {
                /* Fallback */
            }
            const defaultPath = vscode.workspace
                .getConfiguration("python", resource)
                .get("defaultInterpreterPath");
            if (defaultPath)
                return defaultPath;
            for (const cmd of ["python3", "python"]) {
                try {
                    (0, child_process_1.execSync)(`${cmd} --version`, { stdio: "ignore" });
                    return cmd;
                }
                catch {
                    /* Fallback */
                }
            }
            throw new Error("Could not find a valid Python interpreter.");
        }
        function checkPythonPackages(pythonExecutable) {
            const requiredPackages = [
                "parso",
                "astroid",
                "networkx",
                "astor",
                "google-genai",
            ];
            return {
                missing: requiredPackages.filter((pkg) => {
                    try {
                        (0, child_process_1.execSync)(`"${pythonExecutable}" -c "import ${pkg.split("-")[0]}"`, {
                            stdio: "pipe",
                        });
                        return false;
                    }
                    catch {
                        return true;
                    }
                }),
            };
        }
        async function installMissingPackages(pythonExecutable, missingPackages) {
            const installCmd = `"${pythonExecutable}" -m pip install ${missingPackages.join(" ")}`;
            try {
                (0, child_process_1.execSync)(installCmd, { stdio: "pipe" });
                const recheck = checkPythonPackages(pythonExecutable);
                return recheck.missing.length === 0;
            }
            catch (error) {
                outputChannel.appendLine(`Package installation failed: ${error}`);
                return false;
            }
        }
        async function promptInstallPackages(pythonExecutable, missingPackages) {
            const choice = await vscode.window.showWarningMessage(`FindRuntimeErr에 필요한 패키지가 없습니다: ${missingPackages.join(", ")}`, { modal: true }, "자동 설치");
            if (choice === "자동 설치") {
                return await vscode.window.withProgress({
                    location: vscode.ProgressLocation.Notification,
                    title: "Python 패키지 설치 중...",
                }, async (progress) => {
                    progress.report({
                        message: `Installing ${missingPackages.join(", ")}...`,
                    });
                    const success = await installMissingPackages(pythonExecutable, missingPackages);
                    if (success) {
                        vscode.window.showInformationMessage("패키지 설치가 완료되었습니다.");
                        checkedPackages = true;
                    }
                    else {
                        vscode.window.showErrorMessage(`패키지 설치에 실패했습니다. 터미널에서 직접 설치해주세요: pip install ${missingPackages.join(" ")}`);
                    }
                    return success;
                });
            }
            return false;
        }
        // --- 여기가 수정된 부분: runStaticAnalysis와 runDynamicAnalysis를 통합 ---
        async function runAnalysisProcess(scriptName, code, documentUri, mode = "realtime") {
            let pythonExecutable;
            try {
                pythonExecutable = await getSelectedPythonPath(documentUri);
            }
            catch (e) {
                return {
                    errors: [
                        {
                            message: `Python 경로 오류: ${e.message}`,
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
            if (!checkedPackages) {
                const checkResult = checkPythonPackages(pythonExecutable);
                if (checkResult.missing.length > 0) {
                    const installed = await promptInstallPackages(pythonExecutable, checkResult.missing);
                    if (!installed) {
                        return {
                            errors: [
                                {
                                    message: `필수 패키지가 설치되지 않았습니다: ${checkResult.missing.join(", ")}`,
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
            const scriptPath = path.join(context.extensionPath, "scripts", scriptName);
            if (!fs.existsSync(scriptPath)) {
                return {
                    errors: [
                        {
                            message: `분석 스크립트를 찾을 수 없습니다: ${scriptName}`,
                            line: 1,
                            column: 0,
                            errorType: "ScriptNotFoundError",
                        },
                    ],
                    call_graph: null,
                };
            }
            const args = scriptName === "main.py"
                ? [scriptPath, mode, path.dirname(documentUri.fsPath)]
                : [scriptPath];
            return new Promise((resolve) => {
                const proc = (0, child_process_1.spawn)(pythonExecutable, args, {
                    cwd: path.dirname(scriptPath),
                });
                if (scriptName === "dynamic_analyze.py") {
                    dynamicProcess = proc;
                }
                let stdout = "", stderr = "";
                proc.stdin?.write(code);
                proc.stdin?.end();
                proc.stdout?.on("data", (data) => (stdout += data));
                proc.stderr?.on("data", (data) => (stderr += data));
                proc.on("close", (code) => {
                    if (scriptName === "dynamic_analyze.py") {
                        dynamicProcess = null;
                    }
                    if (code !== 0 && !stdout.trim()) {
                        resolve({
                            errors: [
                                {
                                    message: `분석 스크립트 오류 (코드: ${code}): ${stderr}`,
                                    line: 1,
                                    column: 0,
                                    errorType: "ScriptError",
                                },
                            ],
                            call_graph: null,
                        });
                        return;
                    }
                    try {
                        resolve(JSON.parse(stdout.trim() || '{"errors": [], "call_graph": null}'));
                    }
                    catch (e) {
                        resolve({
                            errors: [
                                {
                                    message: `분석 결과 파싱 오류: ${e.message}`,
                                    line: 1,
                                    column: 0,
                                    errorType: "JSONParseError",
                                },
                            ],
                            call_graph: null,
                        });
                    }
                });
                proc.on("error", (err) => {
                    if (scriptName === "dynamic_analyze.py") {
                        dynamicProcess = null;
                    }
                    resolve({
                        errors: [
                            {
                                message: `분석 프로세스 시작 실패: ${err.message}`,
                                line: 1,
                                column: 0,
                                errorType: "SpawnError",
                            },
                        ],
                        call_graph: null,
                    });
                });
            });
        }
        function handleAnalysisResult(documentUri, result, mode) {
            const config = getConfiguration();
            const filteredErrors = result.errors
                .filter((e) => !config.ignoredErrorTypes.includes(e.errorType.toLowerCase()))
                .map((e) => ({ ...e, filePath: documentUri.fsPath }));
            const docUriString = documentUri.toString();
            if (mode === "realtime") {
                realtimeAnalysisResults.set(docUriString, filteredErrors);
            }
            else {
                preciseAnalysisResults.set(docUriString, filteredErrors);
            }
            displayDiagnostics(documentUri, config, filteredErrors);
            webviewManager.updateStaticWebview();
        }
        function displayDiagnostics(documentUri, config, errors) {
            const diagnostics = [];
            errors.forEach((err) => {
                const severity = err.errorType.toUpperCase().startsWith("W")
                    ? vscode.DiagnosticSeverity.Warning
                    : vscode.DiagnosticSeverity.Error;
                if (severity <= config.severityLevel) {
                    const range = createRange(err);
                    const diagnostic = new vscode.Diagnostic(range, err.message, severity);
                    diagnostic.source = "FindRuntimeErr";
                    diagnostic.code = err.errorType;
                    diagnostics.push(diagnostic);
                }
            });
            diagnosticCollection.set(documentUri, diagnostics);
        }
        const createRange = (err) => {
            const line = Math.max(0, err.line - 1);
            const column = Math.max(0, err.column);
            const toLine = Math.max(line, (err.to_line ?? err.line) - 1);
            const endColumn = Math.max(column + 1, err.end_column ?? column + 1);
            return new vscode.Range(line, column, toLine, endColumn);
        };
        const triggerRealtimeAnalysis = (document) => {
            if (document.languageId !== "python" || document.uri.scheme !== "file")
                return;
            if (debounceTimeout)
                clearTimeout(debounceTimeout);
            debounceTimeout = setTimeout(() => {
                const config = getConfiguration();
                if (!config.enable ||
                    document.getText().length < config.minAnalysisLength) {
                    diagnosticCollection.delete(document.uri);
                    return;
                }
                runAnalysisProcess("main.py", document.getText(), document.uri, "realtime").then((result) => handleAnalysisResult(document.uri, result, "realtime"));
            }, debounceDelay);
        };
        context.subscriptions.push(vscode.workspace.onDidChangeTextDocument((e) => e.document.languageId === "python" &&
            triggerRealtimeAnalysis(e.document)));
        context.subscriptions.push(vscode.workspace.onDidOpenTextDocument((doc) => doc.languageId === "python" && triggerRealtimeAnalysis(doc)));
        context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor((editor) => editor?.document.languageId === "python" &&
            triggerRealtimeAnalysis(editor.document)));
        context.subscriptions.push(vscode.workspace.onDidCloseTextDocument((doc) => diagnosticCollection.delete(doc.uri)));
        context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration("findRuntimeErr") ||
                e.affectsConfiguration("python.defaultInterpreterPath")) {
                checkedPackages = false;
                if (vscode.window.activeTextEditor)
                    triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
            }
        }));
        // --- 명령어 등록 ---
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.showStaticAnalysis", () => webviewManager.createStaticAnalysisPanel()));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.showDynamicAnalysis", () => webviewManager.createDynamicAnalysisPanel()));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", async () => {
            const editor = vscode.window.activeTextEditor;
            if (editor?.document.languageId === "python") {
                await vscode.window.withProgress({
                    location: vscode.ProgressLocation.Notification,
                    title: "FindRuntimeErr: 정밀 분석 중...",
                }, async () => {
                    const result = await runAnalysisProcess("main.py", editor.document.getText(), editor.document.uri, "static");
                    handleAnalysisResult(editor.document.uri, result, "static");
                    vscode.window.showInformationMessage(`정밀 분석 완료. ${result.errors.length}개 이슈 발견.`);
                });
            }
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.toggleRealtimeAnalysis", async () => {
            const config = vscode.workspace.getConfiguration("findRuntimeErr");
            const currentEnable = config.get("enable", true);
            await config.update("enable", !currentEnable, vscode.ConfigurationTarget.Workspace);
            webviewManager.updateRealtimeStatus(!currentEnable);
            vscode.window.showInformationMessage(`실시간 분석이 ${!currentEnable ? "활성화" : "비활성화"}되었습니다.`);
            if (currentEnable) {
                if (vscode.window.activeTextEditor)
                    diagnosticCollection.delete(vscode.window.activeTextEditor.document.uri);
            }
            else {
                if (vscode.window.activeTextEditor)
                    triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
            }
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.sendRealtimeStatus", () => {
            const isEnable = vscode.workspace
                .getConfiguration("findRuntimeErr")
                .get("enable", true);
            webviewManager.updateRealtimeStatus(isEnable);
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", async () => {
            const editor = vscode.window.activeTextEditor;
            if (editor?.document.languageId !== "python") {
                vscode.window.showWarningMessage("동적 분석을 실행할 Python 파일을 열어주세요.");
                throw new Error("No active Python file.");
            }
            try {
                webviewManager.updateDynamicAnalysisProgress(1, "active", "환경 준비 및 함수 분석...");
                const result = await runAnalysisProcess("dynamic_analyze.py", editor.document.getText(), editor.document.uri);
                webviewManager.updateDynamicAnalysisProgress(1, "completed", "함수 분석 완료");
                webviewManager.updateDynamicAnalysisProgress(2, "completed", "AI 테스트케이스 생성 완료");
                webviewManager.updateDynamicAnalysisProgress(3, "completed", "테스트 실행 완료");
                dynamicAnalysisResults.set(editor.document.uri.toString(), result);
                webviewManager.updateDynamicAnalysisResult(result);
            }
            catch (e) {
                webviewManager.handleDynamicAnalysisError(1, `분석 실행 실패: ${e.message}`);
            }
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.killPythonProcess", () => {
            if (dynamicProcess) {
                dynamicProcess.kill();
                vscode.window.showInformationMessage("동적 분석 프로세스가 중단되었습니다.");
                webviewManager.handleDynamicAnalysisError(3, "사용자에 의해 중단됨");
            }
        }));
        if (vscode.window.activeTextEditor) {
            triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
        }
    }
    catch (e) {
        vscode.window.showErrorMessage(`FindRuntimeErr 활성화 실패: ${e.message}.`);
    }
}
function deactivate() {
    if (debounceTimeout)
        clearTimeout(debounceTimeout);
    if (dynamicProcess)
        dynamicProcess.kill();
}
//# sourceMappingURL=extension.js.map