"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
// src/extension.ts
const vscode = require("vscode");
const child_process_1 = require("child_process");
const path = require("path");
// --- 전역 변수 ---
let outputChannel;
let diagnosticCollection;
let lastUsedPythonExecutable = null;
let checkedPackages = false;
let debounceTimeout = null;
const inlayHintsCache = new Map();
// --- 확장 기능 활성화 함수 ---
function activate(context) {
    try {
        outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
        diagnosticCollection =
            vscode.languages.createDiagnosticCollection("findRuntimeErr");
        context.subscriptions.push(diagnosticCollection);
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
                case "error":
                default:
                    diagnosticSeverity = vscode.DiagnosticSeverity.Error;
                    break;
            }
            return {
                enable: config.get("enable", true),
                severityLevel: diagnosticSeverity,
                enableDynamicAnalysis: config.get("enableDynamicAnalysis", false),
                ignoredErrorTypes: config
                    .get("ignoredErrorTypes", [])
                    .map((t) => t.toLowerCase()),
                minAnalysisLength: config.get("minAnalysisLength", 10),
                pythonPath: config.get("pythonPath", null),
                enableInlayHints: config.get("enableInlayHints", true),
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
            const requiredPackages = ["parso", "astroid", "networkx"];
            const missingPackages = requiredPackages.filter((pkg) => {
                try {
                    (0, child_process_1.execSync)(`"${pythonExecutable}" -m pip show "${pkg}"`, {
                        stdio: "pipe",
                    });
                    return false;
                }
                catch {
                    return true;
                }
            });
            return { missing: missingPackages };
        }
        async function runAnalysisProcess(code, mode, documentUri) {
            let pythonExecutable;
            try {
                pythonExecutable = await getSelectedPythonPath(documentUri);
            }
            catch (e) {
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
            return new Promise((resolve) => {
                try {
                    if (!checkedPackages) {
                        const checkResult = checkPythonPackages(pythonExecutable);
                        if (checkResult.missing.length > 0) {
                            resolve({
                                errors: [
                                    {
                                        message: `Missing packages: ${checkResult.missing.join(", ")}. Please install them.`,
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
                    const scriptPath = path.join(context.extensionPath, "scripts", "main.py");
                    const baseDir = documentUri
                        ? path.dirname(documentUri.fsPath)
                        : context.extensionPath;
                    const args = [scriptPath, mode, baseDir];
                    const spawnOptions = {
                        cwd: path.dirname(scriptPath),
                    };
                    const pythonProcess = (0, child_process_1.spawn)(pythonExecutable, args, spawnOptions);
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
                            const result = JSON.parse(stdoutData.trim());
                            if (result && Array.isArray(result.errors)) {
                                resolve(result);
                            }
                            else {
                                throw new Error("Invalid analysis result format.");
                            }
                        }
                        catch (e) {
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
                }
                catch (e) {
                    resolve({
                        errors: [
                            {
                                message: `Error setting up analysis: ${e.message}`,
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
        function handleAnalysisResult(documentUri, config, result) {
            if (!result || !Array.isArray(result.errors))
                return;
            const filteredErrors = result.errors.filter((err) => !config.ignoredErrorTypes.includes(err.errorType.toLowerCase()));
            const inlayHints = createInlayHints(filteredErrors, config);
            inlayHintsCache.set(documentUri.toString(), inlayHints);
            displayDiagnostics(documentUri, config, filteredErrors);
        }
        const createRange = (err) => {
            const line = Math.max(0, err.line - 1);
            const column = Math.max(0, err.column);
            const toLine = Math.max(line, (err.to_line ?? err.line) - 1);
            const endColumn = Math.max(column + 1, err.end_column ?? column + 1);
            return new vscode.Range(line, column, toLine, endColumn);
        };
        function createInlayHints(errors, config) {
            const hints = [];
            if (!config.enableInlayHints)
                return hints;
            for (const err of errors) {
                const { severity } = getSeverity(err.errorType);
                if (severity <= config.severityLevel) {
                    let hintText;
                    if (err.errorType === "W0701")
                        hintText = `// Potential infinite loop`;
                    else if (err.errorType === "W0801")
                        hintText = `// Potential recursion`;
                    if (hintText) {
                        const range = createRange(err);
                        const position = new vscode.Position(range.start.line, range.end.character);
                        const hint = new vscode.InlayHint(position, hintText);
                        hint.paddingLeft = true;
                        hints.push(hint);
                    }
                }
            }
            return hints;
        }
        function getSeverity(errorType) {
            if (errorType.toUpperCase().startsWith("E"))
                return { severity: vscode.DiagnosticSeverity.Error };
            if (errorType.toUpperCase().startsWith("W"))
                return { severity: vscode.DiagnosticSeverity.Warning };
            return { severity: vscode.DiagnosticSeverity.Information };
        }
        function displayDiagnostics(documentUri, config, errors) {
            const diagnostics = [];
            errors.forEach((err) => {
                const { severity } = getSeverity(err.errorType);
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
        function clearPreviousAnalysis(documentUri) {
            diagnosticCollection.delete(documentUri);
            inlayHintsCache.delete(documentUri.toString());
        }
        const hoverProvider = vscode.languages.registerHoverProvider({ language: "python" }, {
            provideHover(document, position) {
                const diagnosticsAtPos = diagnosticCollection
                    .get(document.uri)
                    ?.filter((d) => d.range.contains(position));
                if (!diagnosticsAtPos?.length)
                    return undefined;
                const hoverContent = new vscode.MarkdownString(diagnosticsAtPos
                    .map((d) => `**[${d.code}]** ${d.message}`)
                    .join("\n\n---\n\n"));
                return new vscode.Hover(hoverContent, diagnosticsAtPos[0].range);
            },
        });
        context.subscriptions.push(hoverProvider);
        const inlayHintsProvider = vscode.languages.registerInlayHintsProvider({ language: "python" }, {
            provideInlayHints: (doc) => inlayHintsCache.get(doc.uri.toString()) || [],
        });
        context.subscriptions.push(inlayHintsProvider);
        const triggerRealtimeAnalysis = (document) => {
            if (document.languageId !== "python" || document.uri.scheme !== "file")
                return;
            if (debounceTimeout)
                clearTimeout(debounceTimeout);
            debounceTimeout = setTimeout(() => {
                const config = getConfiguration();
                if (!config.enable ||
                    document.getText().length < config.minAnalysisLength) {
                    clearPreviousAnalysis(document.uri);
                    return;
                }
                clearPreviousAnalysis(document.uri);
                runAnalysisProcess(document.getText(), "realtime", document.uri)
                    .then((result) => handleAnalysisResult(document.uri, config, result))
                    .catch(() => { }); // Errors are handled inside runAnalysisProcess
            }, debounceDelay);
        };
        context.subscriptions.push(vscode.workspace.onDidChangeTextDocument((event) => {
            if (vscode.window.activeTextEditor?.document === event.document)
                triggerRealtimeAnalysis(event.document);
        }));
        context.subscriptions.push(vscode.workspace.onDidOpenTextDocument((doc) => {
            if (doc.languageId === "python")
                triggerRealtimeAnalysis(doc);
        }));
        context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor((editor) => {
            if (editor?.document.languageId === "python")
                triggerRealtimeAnalysis(editor.document);
        }));
        context.subscriptions.push(vscode.workspace.onDidCloseTextDocument((doc) => clearPreviousAnalysis(doc.uri)));
        context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration("findRuntimeErr") ||
                e.affectsConfiguration("python.defaultInterpreterPath")) {
                checkedPackages = false;
                if (vscode.window.activeTextEditor)
                    triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
            }
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", async () => {
            const editor = vscode.window.activeTextEditor;
            if (editor?.document.languageId === "python") {
                clearPreviousAnalysis(editor.document.uri);
                const config = getConfiguration();
                await vscode.window.withProgress({
                    location: vscode.ProgressLocation.Notification,
                    title: "FindRuntimeErr: 정적 분석 중...",
                }, async () => {
                    const result = await runAnalysisProcess(editor.document.getText(), "static", editor.document.uri);
                    handleAnalysisResult(editor.document.uri, config, result);
                    vscode.window.showInformationMessage(`정적 분석 완료. ${result.errors.length}개 이슈 발견.`);
                });
            }
        }));
        if (vscode.window.activeTextEditor)
            triggerRealtimeAnalysis(vscode.window.activeTextEditor.document);
    }
    catch (e) {
        vscode.window.showErrorMessage(`FindRuntimeErr failed to activate: ${e.message}.`);
    }
}
function deactivate() {
    if (debounceTimeout)
        clearTimeout(debounceTimeout);
}
//# sourceMappingURL=extension.js.map