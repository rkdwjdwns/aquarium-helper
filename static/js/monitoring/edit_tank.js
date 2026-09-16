const APP_CONFIG = document.getElementById('editTankConfig').dataset;
(function () {
  const form = document.getElementById('chatbotForm');
  const input = document.getElementById('chatbotInput');
  const messages = document.getElementById('chatbotMessages');

  function addBubble(text, sender) {
    const div = document.createElement('div');
    div.className = 'chatbot-bubble' + (sender === 'user' ? ' user' : '');
    div.innerHTML = String(text).replace(/\n/g, '<br>');
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;

    addBubble(message, 'user');
    input.value = '';

    const csrftoken = form.querySelector('[name=csrfmiddlewaretoken]').value;

    try {
      const res = await fetch(APP_CONFIG.chatbotUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: message })
      });
      const data = await res.json();

      if (data.status === 'success') {
        addBubble(data.reply, 'bot');
      } else {
        addBubble(data.message || '오류가 발생했습니다.', 'bot');
      }
    } catch (err) {
      addBubble('서버와 통신할 수 없습니다.', 'bot');
    }
  });
})();
