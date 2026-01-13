// Initialize chatbot - create icon and chatbox
document.addEventListener('DOMContentLoaded', function() {
    const chatbot = document.getElementById('chatbot');
    
    if (!chatbot) return;
    
    // Create chatbot icon (visible when closed)
    let chatbotIcon = document.getElementById('chatbot-icon');
    if (!chatbotIcon) {
        chatbotIcon = document.createElement('button');
        chatbotIcon.id = 'chatbot-icon';
        chatbotIcon.innerHTML = '💬';
        chatbotIcon.setAttribute('aria-label', 'Open chatbot');
        chatbot.appendChild(chatbotIcon);
    }
    
    // Create chatbot container (visible when open)
    let chatbotContainer = document.getElementById('chatbot-container');
    if (!chatbotContainer) {
        chatbotContainer = document.createElement('div');
        chatbotContainer.id = 'chatbot-container';
        
        // Create header with close button
        const header = document.createElement('div');
        header.id = 'chatbot-header';
        header.innerHTML = '<h3>💬 Travel Assistant</h3>';
        
        const closeBtn = document.createElement('button');
        closeBtn.id = 'chatbot-close';
        closeBtn.innerHTML = '×';
        closeBtn.setAttribute('aria-label', 'Close chatbot');
        header.appendChild(closeBtn);
        chatbotContainer.appendChild(header);
        
        // Create chat body
        const chatBody = document.createElement('div');
        chatBody.id = 'chat-body';
        chatbotContainer.appendChild(chatBody);
        
        // Create input
        const input = document.createElement('input');
        input.id = 'chat-input';
        input.type = 'text';
        input.placeholder = 'Type a message...';
        chatbotContainer.appendChild(input);
        
        chatbot.appendChild(chatbotContainer);
    }
    
    const chatBody = document.getElementById('chat-body');
    const chatInput = document.getElementById('chat-input');
    const closeBtn = document.getElementById('chatbot-close');
    
    // Toggle chatbot open/close
    function toggleChatbot() {
        chatbotContainer.classList.toggle('open');
        chatbotIcon.style.display = chatbotContainer.classList.contains('open') ? 'none' : 'flex';
        if (chatbotContainer.classList.contains('open')) {
            chatInput.focus();
        }
    }
    
    // Open chatbot when icon is clicked
    chatbotIcon.addEventListener('click', toggleChatbot);
    
    // Close chatbot when close button is clicked
    if (closeBtn) {
        closeBtn.addEventListener('click', toggleChatbot);
    }
    
    // Handle Enter key in input
    if (chatInput) {
        chatInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && chatInput.value.trim()) {
                const message = chatInput.value.trim();
                
                // Add user message to chat
                const userDiv = document.createElement('div');
                userDiv.className = 'user-msg';
                userDiv.textContent = 'You: ' + message;
                chatBody.appendChild(userDiv);
                
                // Clear input
                chatInput.value = '';
                
                // Scroll to bottom
                chatBody.scrollTop = chatBody.scrollHeight;
                
                // Fetch response
                fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: message})
                })
                .then(res => {
                    if (!res.ok) {
                        throw new Error(`HTTP error! status: ${res.status}`);
                    }
                    return res.json();
                })
                .then(data => {
                    // Add bot response to chat
                    const botDiv = document.createElement('div');
                    botDiv.className = 'bot-msg';
                    botDiv.textContent = 'Bot: ' + (data.reply || 'I apologize, but I could not generate a response.');
                    chatBody.appendChild(botDiv);
                    
                    // Scroll to bottom
                    chatBody.scrollTop = chatBody.scrollHeight;
                })
                .catch(error => {
                    console.error('Error:', error);
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'bot-msg';
                    errorDiv.style.color = '#e74c3c';
                    errorDiv.textContent = 'Error: Could not get response. Please try again.';
                    chatBody.appendChild(errorDiv);
                    
                    // Scroll to bottom
                    chatBody.scrollTop = chatBody.scrollHeight;
                });
            }
        });
    }
});
