const vscode = acquireVsCodeApi();

function updateCurrentFile(filePath) {
    const filePathElement = document.getElementById('currentFilePath');
    if (filePath) {
        const fileName = filePath.split(/[\\/]/).pop();
        filePathElement.textContent = `${fileName} (${filePath})`;
        filePathElement.classList.remove('no-file');
    } else {
        filePathElement.textContent = '분석할 Python 파일을 열어주세요.';
        filePathElement.classList.add('no-file');
    }
}

function updateProgress(step, status, text) {
    const stepElement = document.getElementById(`step${step}`);
    if (stepElement) {
        stepElement.className = `step-item ${status}`;
        stepElement.querySelector('span:last-child').textContent = text;
        const icons = { pending: '⚪', active: '🔄', completed: '✅', error: '❌' };
        stepElement.querySelector('.step-icon').textContent = icons[status] || '⚪';
    }
    const progressPercent = (status === 'completed' || status === 'error') ? (step / 3) * 100 : ((step - 1) / 3) * 100;
    document.getElementById('progressFill').style.width = `${progressPercent}%`;
}

function updateOverallProgressText(text) {
    document.getElementById('progressText').textContent = text;
}

function showProgress() {
    document.getElementById('progressContainer').style.display = 'block';
    for (let i = 1; i <= 3; i++) {
        updateProgress(i, 'pending', document.getElementById(`step${i}`).querySelector('span:last-child').textContent);
    }
    document.getElementById('progressFill').style.width = '0%';
    updateOverallProgressText('분석 준비 중...');
}

function setButtonsState(isAnalyzing) {
    const runBtn = document.getElementById('runDynamicAnalysisBtn');
    const killBtn = document.getElementById('killBtn');
    runBtn.disabled = isAnalyzing;
    runBtn.textContent = isAnalyzing ? '분석 중...' : 'AI 테스트 실행';
    killBtn.style.display = isAnalyzing ? 'inline-block' : 'none';
}

function renderTestResults(results) {
    const container = document.getElementById('testResults');
    if (!results || results.length === 0) {
        container.innerHTML = '<div class="no-tests">생성 및 실행된 테스트 케이스가 없습니다.</div>';
        return;
    }
    const resultsHtml = results.map(result => `
        <div class="test-result">
            <div class="function-name">Function: ${result.functionName}</div>
            ${result.testCases.map(tc => `
                <div class="test-case ${tc.success ? 'test-success' : 'test-failure'}">
                    <div class="test-input"><strong>Input:</strong> <code>${JSON.stringify(tc.input)}</code></div>
                    <div class="test-expected"><strong>Expected:</strong> <code>${JSON.stringify(tc.expected)}</code></div>
                    <div class="test-actual"><strong>Actual:</strong> <code>${tc.error ? `ERROR: ${tc.error}` : JSON.stringify(tc.output)}</code></div>
                </div>
            `).join('')}
        </div>
    `).join('');
    container.innerHTML = resultsHtml;
}

function renderErrorList(errors) {
    const container = document.getElementById('errorList');
    if (!errors || errors.length === 0) {
        container.innerHTML = '<div class="no-errors">발견된 런타임 오류가 없습니다.</div>';
        return;
    }
    const errorHtml = errors.map(error => `
        <div class="error-item" data-line="${error.line}" data-column="${error.column}" data-filepath="${error.filePath || ''}">
            <div class="error-header">
                <span class="error-type">${error.errorType || 'Error'}</span>
                <span class="error-location">Line ${error.line || 'N/A'}</span>
            </div>
            <div class="error-message">${error.message}</div>
        </div>
    `).join('');
    container.innerHTML = errorHtml;
    
    container.querySelectorAll('.error-item').forEach(item => {
        item.addEventListener('click', () => {
            vscode.postMessage({
                command: 'goToError',
                line: parseInt(item.dataset.line),
                column: parseInt(item.dataset.column),
                filePath: item.dataset.filepath
            });
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('runDynamicAnalysisBtn').addEventListener('click', () => {
        setButtonsState(true);
        showProgress();
        vscode.postMessage({ command: 'runDynamicAnalysis' });
    });

    document.getElementById('killBtn').addEventListener('click', () => {
        vscode.postMessage({ command: 'killDynamicAnalysis' });
    });

    window.addEventListener('message', event => {
        const message = event.data;
        switch (message.command) {
            case 'updateCurrentFile':
                updateCurrentFile(message.filePath);
                break;
            case 'updateDynamicAnalysisProgress':
                updateProgress(message.step, message.status, message.text);
                updateOverallProgressText(message.overallText);
                break;
            case 'updateDynamicAnalysisResult':
                renderTestResults(message.testResults || []);
                renderErrorList(message.errors || []);
                document.getElementById('dynamicStatus').textContent = `상태: 완료 (오류 ${message.errors?.length || 0}개 발견)`;
                setButtonsState(false);
                break;
            case 'dynamicAnalysisError':
                updateProgress(message.step, 'error', message.text);
                updateOverallProgressText('분석 중 오류 발생');
                document.getElementById('dynamicStatus').textContent = `상태: 오류`;
                setButtonsState(false);
                break;
        }
    });
    
    vscode.postMessage({ command: 'getCurrentFile' });
});