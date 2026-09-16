const APP_CONFIG = document.getElementById('compatibilityConfig').dataset;
function checkFish() {
    const fishList = document.getElementById('fish-input').value;
    const btn = document.getElementById('check-btn');
    const resultArea = document.getElementById('result-area');
    const responseDiv = document.getElementById('ai-response');

    if(!fishList) return alert("어종을 입력해주세요!");

    // 로딩 상태
    btn.disabled = true;
    btn.innerText = "AI 분석 중...";
    resultArea.classList.add('hidden');

    fetch(APP_CONFIG.checkUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': APP_CONFIG.csrf
        },
        body: `fish_list=${encodeURIComponent(fishList)}`
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            responseDiv.innerText = data.result;
            resultArea.classList.remove('hidden');
        } else {
            alert("에러: " + data.message);
        }
    })
    .finally(() => {
        btn.disabled = false;
        btn.innerText = "호환성 분석 시작";
    });
}


document.getElementById('check-btn')?.addEventListener('click',checkFish);
