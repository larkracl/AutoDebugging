"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
// src/extension.ts
const vscode = require("vscode");
const child_process_1 = require("child_process");
const path = require("path");
const fs = require("fs");
let dynamicProcess = null;
let outputChannel;
let diagnosticCollection;
let errorDecorationType;
function activate(context) {
    // --- activate 함수 시작 부분에서 try...catch 시작 ---
    try {
        outputChannel = vscode.window.createOutputChannel("FindRuntimeErr");
        outputChannel.appendLine("FindRuntimeErr 확장 프로그램이 활성화되었습니다.");
        diagnosticCollection =
            vscode.languages.createDiagnosticCollection("findRuntimeErr");
        context.subscriptions.push(diagnosticCollection);
        errorDecorationType = vscode.window.createTextEditorDecorationType({
            textDecoration: "underline wavy green",
        });
        let debounceTimeout = null;
        const debounceDelay = 500;
        let checkedPackages = false; // 패키지 확인 여부 플래그
        let lastUsedPythonExecutable = null; // 마지막 사용 경로
        // --- getConfiguration 함수 ---
        function getConfiguration() {
            try {
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
                    minAnalysisLength: config.get("minAnalysisLength", 10),
                    pythonPath: config.get("pythonPath", null),
                };
            }
            catch (e) {
                console.error("Error getting configuration:", e);
                outputChannel.appendLine(`ERROR getting configuration: ${e.message}\n${e.stack}`);
                // 설정 로드 실패 시 기본값 반환
                return {
                    enable: true,
                    severityLevel: vscode.DiagnosticSeverity.Error,
                    enableDynamicAnalysis: false,
                    ignoredErrorTypes: [],
                    minAnalysisLength: 10,
                    pythonPath: null,
                };
            }
        }
        // --- getSelectedPythonPath 함수 ---
        async function getSelectedPythonPath(resource) {
            const config = getConfiguration(); // 최신 설정 읽기
            try {
                outputChannel.appendLine("[getSelectedPythonPath] Determining Python executable path...");
                // 1. 사용자 설정 확인
                if (config.pythonPath && fs.existsSync(config.pythonPath)) {
                    outputChannel.appendLine(`[getSelectedPythonPath] Using pythonPath from settings: ${config.pythonPath}`);
                    return config.pythonPath;
                }
                // 2. 로컬 환경: VSCode Python 확장 API 시도
                outputChannel.appendLine("[getSelectedPythonPath] Trying VSCode Python extension API.");
                try {
                    const pythonExtension = vscode.extensions.getExtension("ms-python.python");
                    if (pythonExtension) {
                        if (!pythonExtension.isActive) {
                            outputChannel.appendLine("[getSelectedPythonPath] Activating Python extension...");
                            await pythonExtension.activate();
                            outputChannel.appendLine("[getSelectedPythonPath] Python extension activated.");
                        }
                        if (pythonExtension.exports &&
                            pythonExtension.exports.settings &&
                            typeof pythonExtension.exports.settings.getExecutionDetails ===
                                "function") {
                            const effectiveResourceUri = resource ||
                                vscode.window.activeTextEditor?.document.uri ||
                                vscode.workspace.workspaceFolders?.[0]?.uri;
                            outputChannel.appendLine(`[getSelectedPythonPath] Getting execution details for resource: ${effectiveResourceUri?.toString()}`);
                            const executionDetails = pythonExtension.exports.settings.getExecutionDetails(effectiveResourceUri);
                            if (executionDetails?.execCommand?.[0]) {
                                const vscodePythonPath = executionDetails.execCommand[0];
                                try {
                                    outputChannel.appendLine(`[getSelectedPythonPath] Checking path from Python extension: ${vscodePythonPath}`);
                                    (0, child_process_1.execSync)(`"${vscodePythonPath}" --version`); // 경로 유효성 검사
                                    outputChannel.appendLine(`[getSelectedPythonPath] Using valid Python path from VSCode Python extension: ${vscodePythonPath}`);
                                    return vscodePythonPath;
                                }
                                catch (error) {
                                    outputChannel.appendLine(`[getSelectedPythonPath] Path from VSCode Python extension is invalid: ${vscodePythonPath}. Error: ${error}`);
                                }
                            }
                            else {
                                outputChannel.appendLine(`[getSelectedPythonPath] Could not get valid execution details.`);
                            }
                        }
                        else {
                            outputChannel.appendLine(`[getSelectedPythonPath] VSCode Python extension exports or settings not available.`);
                        }
                    }
                    else {
                        outputChannel.appendLine(`[getSelectedPythonPath] VSCode Python extension not found.`);
                    }
                }
                catch (err) {
                    outputChannel.appendLine(`[getSelectedPythonPath] Error accessing Python extension API: ${err.message}`);
                }
                // 3. 최후의 수단: PATH에서 'python3' 또는 'python' 찾기
                outputChannel.appendLine("[getSelectedPythonPath] Falling back to 'python3' or 'python' command.");
                try {
                    (0, child_process_1.execSync)("python3 --version");
                    outputChannel.appendLine("[getSelectedPythonPath] Using 'python3' from PATH.");
                    return "python3";
                }
                catch (error) {
                    outputChannel.appendLine("[getSelectedPythonPath] 'python3' command failed. Trying 'python'.");
                    try {
                        (0, child_process_1.execSync)("python --version");
                        outputChannel.appendLine("[getSelectedPythonPath] Using 'python' from PATH.");
                        return "python";
                    }
                    catch (pyError) {
                        outputChannel.appendLine("[getSelectedPythonPath] 'python' command also failed.");
                        throw new Error("Could not find a valid Python interpreter ('python3' or 'python'). Please configure 'findRuntimeErr.pythonPath' setting.");
                    }
                }
            }
            catch (e) {
                console.error("Error determining Python executable path:", e);
                outputChannel.appendLine(`ERROR determining Python executable path: ${e.message}\n${e.stack}`);
                throw e; // 경로 결정 실패 시 에러 다시 throw
            }
        }
        // --- checkPythonPackages 함수 ---
        function checkPythonPackages(pythonExecutable, packages) {
            const missingPackages = [];
            let checkError;
            outputChannel.appendLine(`[checkPackages] Checking for packages using: ${pythonExecutable}`);
            for (const pkg of packages) {
                try {
                    const command = `"${pythonExecutable}" -m pip show ${pkg}`;
                    outputChannel.appendLine(`[checkPackages] Running: ${command}`);
                    (0, child_process_1.execSync)(command);
                    outputChannel.appendLine(`[checkPackages] Package found: ${pkg}`);
                }
                catch (error) {
                    outputChannel.appendLine(`[checkPackages] Package not found: ${pkg}. Status: ${error.status}`);
                    if (error.stderr) {
                        outputChannel.appendLine(`[checkPackages] Stderr: ${error.stderr.toString()}`);
                    }
                    if (error.stdout) {
                        outputChannel.appendLine(`[checkPackages] Stdout: ${error.stdout.toString()}`);
                    }
                    missingPackages.push(pkg);
                    const errorMsg = error.stderr?.toString() || error.message || "";
                    if (errorMsg.includes("No such file or directory") ||
                        errorMsg.includes("command not found") ||
                        errorMsg.includes("not recognized")) {
                        checkError = `Failed to run Python ('${pythonExecutable}'). Is it installed and in PATH, or is the configured path correct?`;
                        outputChannel.appendLine(`[checkPackages] Python check failed: ${checkError}`);
                        break;
                    }
                }
            }
            // --- 함수 마지막에 명시적인 return 문 추가 ---
            return { missing: missingPackages, error: checkError };
        }
        // --- runAnalysisProcess 함수 ---
        async function runAnalysisProcess(code, mode, documentUri) {
            let pythonExecutable;
            try {
                pythonExecutable = await getSelectedPythonPath(documentUri); // getSelectedPythonPath 사용
            }
            catch (e) {
                outputChannel.appendLine(`[runAnalysisProcess] Failed to get Python executable path: ${e.message}`);
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
                    outputChannel.appendLine(`[runAnalysisProcess] Checking packages with: ${pythonExecutable}`);
                    const requiredPackages = ["astroid", "networkx"];
                    const checkResult = checkPythonPackages(pythonExecutable, requiredPackages);
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
                        checkedPackages = true; // 오류 발생 시 다시 체크 안 함
                    }
                    if (proceedAnalysis && !checkedPackages) {
                        checkedPackages = true;
                    }
                    if (!proceedAnalysis) {
                        outputChannel.appendLine(`[runAnalysisProcess] Aborting analysis due to missing packages.`);
                        // 위에서 이미 resolve 했으므로 여기서 추가 resolve 필요 없음
                        return;
                    }
                    const extensionRootPath = context.extensionPath;
                    const scriptDir = path.join(extensionRootPath, "scripts");
                    const mainScriptPath = path.join(scriptDir, "main.py");
                    if (!fs.existsSync(mainScriptPath)) {
                        throw new Error(`main.py script not found at path: ${mainScriptPath}`);
                    }
                    const spawnOptions = { cwd: scriptDir };
                    outputChannel.appendLine(`[runAnalysisProcess] Spawning: "${pythonExecutable}" "${mainScriptPath}" ${mode} in ${scriptDir}`);
                    const pythonProcess = (0, child_process_1.spawn)(pythonExecutable, [mainScriptPath, mode], spawnOptions);
                    outputChannel.appendLine(`[runAnalysisProcess] Python process object created.`);
                    let stdoutData = "";
                    let stderrData = "";
                    pythonProcess.stdin.write(code);
                    pythonProcess.stdin.end();
                    outputChannel.appendLine(`[runAnalysisProcess] Sent code to Python process stdin.`);
                    pythonProcess.stdout.on("data", (data) => {
                        stdoutData += data;
                    });
                    pythonProcess.stderr.on("data", (data) => {
                        stderrData += data;
                        outputChannel.appendLine(`[Py Stderr] ${data}`);
                    });
                    pythonProcess.on("close", (closeCode) => {
                        try {
                            outputChannel.appendLine(`[runAnalysisProcess] Python process 'close' event. Exit code: ${closeCode}`);
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
                                    }
                                    catch { }
                                }
                                if (stderrData.trim() &&
                                    !errorDetail.includes(stderrData.trim())) {
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
                            outputChannel.appendLine(`[runAnalysisProcess] Raw stdout (${mode}): ${stdoutData}`);
                            if (!stdoutData.trim()) {
                                resolve({ errors: [], call_graph: null });
                                return;
                            }
                            const result = JSON.parse(stdoutData);
                            if (result && Array.isArray(result.errors)) {
                                resolve(result);
                            }
                            else {
                                resolve({
                                    errors: [
                                        {
                                            message: "Invalid analysis result format. 'errors' key missing/not array.",
                                            line: 1,
                                            column: 0,
                                            errorType: "InvalidFormatError",
                                        },
                                    ],
                                    call_graph: null,
                                });
                            }
                        }
                        catch (parseError) {
                            resolve({
                                errors: [
                                    {
                                        message: `Error parsing analysis results: ${parseError.message}. Raw: ${stdoutData.substring(0, 100)}...`,
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
                        outputChannel.appendLine(`[runAnalysisProcess] Python process 'error' event: ${err.message}`);
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
                }
                catch (e) {
                    console.error("Error in runAnalysisProcess setup/spawn:", e);
                    outputChannel.appendLine(`ERROR in runAnalysisProcess setup/spawn: ${e.message}\n${e.stack}`);
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
        async function runDynamicAnalysisProcess(code, documentUri) {
            let pythonExecutable;
            try {
                pythonExecutable = await getSelectedPythonPath(documentUri);
            }
            catch (e) {
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
            const pkgCheck = checkPythonPackages(pythonExecutable, [
                "astroid",
                "networkx",
            ]);
            if (pkgCheck.error) {
                return {
                    errors: [
                        {
                            message: pkgCheck.error,
                            line: 1,
                            column: 0,
                            errorType: "MissingDependencyError",
                        },
                    ],
                    call_graph: null,
                };
            }
            if (pkgCheck.missing.length > 0) {
                return {
                    errors: [
                        {
                            message: `Missing packages: ${pkgCheck.missing.join(", ")}. Please install in ${pythonExecutable}.`,
                            line: 1,
                            column: 0,
                            errorType: "MissingDependencyError",
                        },
                    ],
                    call_graph: null,
                };
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
                const spawnOpts = { cwd: scriptDir };
                outputChannel.appendLine(`[runDynamicAnalysisProcess] Spawning: "${pythonExecutable}" "${scriptPath}"`);
                dynamicProcess = (0, child_process_1.spawn)(pythonExecutable, [scriptPath], spawnOpts);
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
                    outputChannel.appendLine(`[runDynamicAnalysisProcess] Process exited with code ${code}`);
                    outputChannel.appendLine(`[runDynamicAnalysisProcess] RAW STDOUT: ${stdoutData}`);
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
                        const result = JSON.parse(stdoutData);
                        resolve(result);
                    }
                    catch (e) {
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
        // --- 분석 로직 (analyzeCode) ---
        async function analyzeCode(code, documentUri, mode = "realtime", showProgress = false) {
            try {
                outputChannel.appendLine(`[analyzeCode] Function called. Mode: ${mode}, URI: ${documentUri.fsPath}`);
                const config = getConfiguration();
                if (mode === "realtime") {
                    if (!config.enable) {
                        outputChannel.appendLine("[analyzeCode] Real-time analysis disabled.");
                        clearPreviousAnalysis(documentUri);
                        return;
                    }
                    if (code.length < config.minAnalysisLength) {
                        outputChannel.appendLine(`[analyzeCode] Code length (${code.length}) < minAnalysisLength (${config.minAnalysisLength}). Skipping.`);
                        clearPreviousAnalysis(documentUri);
                        return;
                    }
                }
                clearPreviousAnalysis(documentUri);
                let analysisResult = null;
                if (showProgress) {
                    // 상세 정적 분석 Progress
                    await vscode.window.withProgress({
                        location: vscode.ProgressLocation.Notification,
                        title: "FindRuntimeErr: 정적 분석 실행 중...",
                        cancellable: false,
                    }, async (progress) => {
                        // location 추가
                        try {
                            progress.report({ message: "코드 분석 중..." });
                            analysisResult = await runAnalysisProcess(code, "static", documentUri);
                            handleAnalysisResult(documentUri, config, analysisResult, "static");
                            const scriptErrors = analysisResult.errors.filter((e) => !["SyntaxError"].includes(e.errorType) &&
                                e.errorType.endsWith("Error"));
                            if (scriptErrors.length > 0) {
                                vscode.window.showWarningMessage(`FindRuntimeErr: 정적 분석 중 문제 발생 (${scriptErrors[0].errorType}). Problems 패널 확인.`);
                            }
                            else {
                                vscode.window.showInformationMessage(`FindRuntimeErr: 정적 분석 완료. ${analysisResult.errors.length}개의 잠재적 오류 발견.`);
                            }
                            outputChannel.appendLine(`[analyzeCode] Static analysis processed. ${analysisResult.errors.length} potential issues found.`);
                        }
                        catch (error) {
                            console.error("Static analysis failed unexpectedly within withProgress:", error);
                            outputChannel.appendLine(`[analyzeCode] Unexpected error during static analysis progress: ${error.message}`);
                            handleAnalysisResult(documentUri, config, {
                                errors: [
                                    {
                                        message: `Unexpected static analysis error: ${error.message}`,
                                        line: 1,
                                        column: 0,
                                        errorType: "UnexpectedError",
                                    },
                                ],
                                call_graph: null,
                            }, "static");
                        }
                    });
                }
                else {
                    // 실시간 분석
                    try {
                        analysisResult = await runAnalysisProcess(code, "realtime", documentUri);
                        handleAnalysisResult(documentUri, config, analysisResult, "realtime");
                    }
                    catch (error) {
                        console.error("Real-time analysis failed unexpectedly:", error);
                        outputChannel.appendLine(`[analyzeCode] Real-time analysis failed unexpectedly: ${error.message}`);
                        handleAnalysisResult(documentUri, config, {
                            errors: [
                                {
                                    message: `Analysis failed: ${error.message}`,
                                    line: 1,
                                    column: 0,
                                    errorType: "AnalysisErrorRT",
                                },
                            ],
                            call_graph: null,
                        }, "realtime");
                    }
                }
                if (!analysisResult) {
                    outputChannel.appendLine(`[analyzeCode] Analysis finished with null result (${mode}).`);
                    clearPreviousAnalysis(documentUri);
                }
            }
            catch (e) {
                console.error("Error in analyzeCode:", e);
                outputChannel.appendLine(`ERROR in analyzeCode: ${e.message}\n${e.stack}`);
            }
        }
        // --- 결과 처리 및 표시 함수 ---
        function handleAnalysisResult(documentUri, config, result, mode) {
            /* ... 이전 최종 코드와 동일 ... */
        }
        function displayDiagnostics(documentUri, config, errors) {
            /* ... 이전 최종 코드와 동일 ... */
        }
        function clearPreviousAnalysis(documentUri) {
            /* ... 이전 최종 코드와 동일 ... */
        }
        // --- Hover Provider (provideHover 반환 타입 수정됨) ---
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
                            hoverContent.appendMarkdown(`**[FindRuntimeErr] ${diagnostic.code || "Error"}**\n\n`);
                            hoverContent.appendMarkdown(`${diagnostic.message.split(" : ")[0].trim()}\n\n`);
                            if (diagnostic.source === "FindRuntimeErr" &&
                                diagnostic.message.startsWith("FindRuntimeErr Internal Error:")) {
                                hoverContent.appendMarkdown(`\n\n---\n\n**Internal Info:**\n${diagnostic.message}`);
                            }
                            return new vscode.Hover(hoverContent, diagnostic.range);
                        }
                    }
                    return undefined;
                }
                catch (e) {
                    console.error("Error in HoverProvider:", e);
                    outputChannel.appendLine(`ERROR in HoverProvider: ${e.message}\n${e.stack}`);
                    return undefined; // catch 블록에서도 undefined 반환
                }
            },
        });
        context.subscriptions.push(hoverProvider);
        // --- 이벤트 리스너 및 명령어 등록 ---
        vscode.workspace.onDidChangeTextDocument((event) => {
            try {
                if (event.document.languageId === "python") {
                    /* ... Debounce ... analyzeCode(..., event.document.uri) */
                }
            }
            catch (e) {
                /* ... */
            }
        });
        vscode.workspace.onDidOpenTextDocument((document) => {
            try {
                if (document.languageId === "python") {
                    analyzeCode(document.getText(), document.uri);
                }
            }
            catch (e) {
                /* ... */
            }
        });
        vscode.workspace.onDidChangeConfiguration((e) => {
            try {
                if (e.affectsConfiguration("findRuntimeErr")) {
                    checkedPackages = false;
                    if (vscode.window.activeTextEditor?.document.languageId === "python") {
                        analyzeCode(vscode.window.activeTextEditor.document.getText(), vscode.window.activeTextEditor.document.uri);
                    }
                }
            }
            catch (e) {
                /* ... */
            }
        });
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.analyzeCurrentFile", () => {
            try {
                const editor = vscode.window.activeTextEditor;
                if (editor?.document.languageId === "python") {
                    analyzeCode(editor.document.getText(), editor.document.uri, "static", true);
                }
                else {
                    /* ... */
                }
            }
            catch (e) {
                /* ... */
            }
        }));
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.runDynamicAnalysis", () => {
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document.languageId === "python") {
                outputChannel.appendLine("[Command] findRuntimeErr.runDynamicAnalysis executed.");
                const config = getConfiguration();
                clearPreviousAnalysis(editor.document.uri);
                runDynamicAnalysisProcess(editor.document.getText(), editor.document.uri)
                    .then((result) => {
                    handleAnalysisResult(editor.document.uri, config, result, "dynamic");
                    // Function-level error summary
                    const summaryCounts = {};
                    result.errors.forEach(err => {
                        const match = err.message.match(/Function `(.+?)` failed/);
                        const fn = match ? match[1] : 'unknown';
                        summaryCounts[fn] = (summaryCounts[fn] || 0) + 1;
                    });
                    outputChannel.appendLine('[Dynamic Analysis Summary]');
                    for (const [fn, cnt] of Object.entries(summaryCounts)) {
                        outputChannel.appendLine(`  ${fn}: ${cnt} error(s)`);
                    }
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
        // Command to kill the running dynamic analysis Python process
        context.subscriptions.push(vscode.commands.registerCommand("findRuntimeErr.killPythonProcess", () => {
            if (dynamicProcess) {
                dynamicProcess.kill();
                outputChannel.appendLine("[Command] Python process killed by user.");
                vscode.window.showInformationMessage("FindRuntimeErr: Python process has been terminated.");
                dynamicProcess = null;
            }
            else {
                vscode.window.showWarningMessage("FindRuntimeErr: No Python process is currently running.");
            }
        }));
        // --- 초기 실행 (async 함수 사용 및 getSelectedPythonPath 호출) ---
        async function runInitialAnalysis() {
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document.languageId === "python") {
                try {
                    const initialConfig = getConfiguration();
                    // getSelectedPythonPath 호출로 변경
                    const initialPython = await getSelectedPythonPath(editor.document.uri); // documentUri 전달
                    if (initialPython) {
                        const pkgsOk = checkPythonPackages(initialPython, [
                            "astroid",
                            "networkx",
                        ]);
                        if (pkgsOk.missing.length === 0 && !pkgsOk.error) {
                            outputChannel.appendLine("[Activate] Analyzing initially active Python file.");
                            await analyzeCode(editor.document.getText(), editor.document.uri);
                        }
                        else {
                            outputChannel.appendLine("[Activate] Initial analysis skipped due to missing packages or Python path error.");
                            const errorMsg = pkgsOk.error ||
                                `Missing packages: ${pkgsOk.missing.join(", ")}. Run 'pip install ...'`;
                            displayDiagnostics(editor.document.uri, initialConfig, [
                                {
                                    message: errorMsg,
                                    line: 1,
                                    column: 0,
                                    errorType: pkgsOk.error
                                        ? "PythonPathError"
                                        : "MissingDependencyError",
                                },
                            ]);
                        }
                    }
                    else {
                        outputChannel.appendLine("[Activate] Could not determine Python path for initial analysis.");
                        displayDiagnostics(editor.document.uri, initialConfig, [
                            {
                                message: "Could not determine Python path for initial analysis. Check Python extension or 'findRuntimeErr.pythonPath' setting.",
                                line: 1,
                                column: 0,
                                errorType: "PythonPathError",
                            },
                        ]);
                    }
                }
                catch (e) {
                    console.error("Error during initial analysis:", e);
                    outputChannel.appendLine(`ERROR during initial analysis: ${e.message}\n${e.stack}`);
                    if (editor) {
                        displayDiagnostics(editor.document.uri, getConfiguration(), [
                            {
                                message: `Initial analysis error: ${e.message}`,
                                line: 1,
                                column: 0,
                                errorType: "InitialAnalysisError",
                            },
                        ]);
                    }
                }
            }
            else {
                outputChannel.appendLine("[Activate] No active Python editor found for initial analysis.");
            }
        }
        // runInitialAnalysis 함수 호출
        runInitialAnalysis();
    }
    catch (e) {
        // activate 함수 자체 오류 처리
        console.error("Error during extension activation:", e);
        vscode.window.showErrorMessage(`FindRuntimeErr failed to activate: ${e.message}`);
    }
} // activate 함수 끝
function deactivate() {
    try {
        if (outputChannel) {
            outputChannel.dispose();
        }
        console.log("FindRuntimeErr extension deactivated.");
    }
    catch (e) {
        console.error("Error during extension deactivation:", e);
    }
}
//# sourceMappingURL=extension.js.map