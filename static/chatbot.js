// AI Travel Chatbot
(function () {
    // Create chatbot UI
    const chatbotHTML = `
        <div id="chatbot-container" style="position: fixed; bottom: 20px; right: 20px; z-index: 1000;">
            <!-- Chatbot Toggle Button -->
            <button id="chatbot-toggle" style="
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border: none;
                color: white;
                font-size: 28px;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                justify-content: center;
            " onmouseover="this.style.transform='scale(1.1)'" onmouseout="this.style.transform='scale(1)'">
                💬
            </button>

            <!-- Chatbot Window -->
            <div id="chatbot-window" style="
                display: none;
                position: absolute;
                bottom: 80px;
                right: 0;
                width: 380px;
                height: 550px;
                background: white;
                border-radius: 16px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.2);
                overflow: hidden;
                flex-direction: column;
            ">
                <!-- Header -->
                <div style="
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                ">
                    <div>
                        <h3 style="margin: 0; font-size: 18px;">🤖 Travel Assistant</h3>
                        <p style="margin: 5px 0 0 0; font-size: 12px; opacity: 0.9;">Powered by Gemini AI</p>
                    </div>
                    <button id="chatbot-close" style="
                        background: rgba(255,255,255,0.2);
                        border: none;
                        color: white;
                        width: 32px;
                        height: 32px;
                        border-radius: 50%;
                        cursor: pointer;
                        font-size: 18px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    ">×</button>
                </div>

                <!-- Messages Container -->
                <div id="chatbot-messages" style="
                    flex: 1;
                    overflow-y: auto;
                    padding: 20px;
                    background: #f8f9fa;
                ">
                    <div class="bot-message" style="
                        background: white;
                        padding: 12px 16px;
                        border-radius: 12px;
                        margin-bottom: 12px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        animation: slideIn 0.3s ease;
                    ">
                        <strong style="color: #667eea;">🤖 AI Assistant</strong>
                        <p style="margin: 8px 0 0 0; color: #333; line-height: 1.5;">
                            Hi! I'm your AI travel assistant. Ask me anything about:
                            <br>• Destination recommendations
                            <br>• Transport options
                            <br>• Travel tips
                            <br>• Best times to visit
                            <br>• Budget planning
                        </p>
                    </div>
                </div>

                <!-- Input Area -->
                <div style="
                    padding: 16px;
                    background: white;
                    border-top: 1px solid #e0e0e0;
                    display: flex;
                    gap: 8px;
                ">
                    <input type="text" id="chatbot-input" placeholder="Ask me anything..." style="
                        flex: 1;
                        padding: 12px 16px;
                        border: 2px solid #e0e0e0;
                        border-radius: 24px;
                        outline: none;
                        font-size: 14px;
                        transition: border-color 0.3s;
                    " onfocus="this.style.borderColor='#667eea'" onblur="this.style.borderColor='#e0e0e0'">
                    <button id="chatbot-send" style="
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        border: none;
                        color: white;
                        width: 44px;
                        height: 44px;
                        border-radius: 50%;
                        cursor: pointer;
                        font-size: 18px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        transition: transform 0.2s;
                    " onmouseover="this.style.transform='scale(1.1)'" onmouseout="this.style.transform='scale(1)'">
                        ➤
                    </button>
                </div>
            </div>
        </div>

        <style>
            @keyframes slideIn {
                from {
                    opacity: 0;
                    transform: translateY(10px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            #chatbot-messages::-webkit-scrollbar {
                width: 6px;
            }

            #chatbot-messages::-webkit-scrollbar-track {
                background: #f1f1f1;
            }

            #chatbot-messages::-webkit-scrollbar-thumb {
                background: #667eea;
                border-radius: 3px;
            }

            .typing-indicator {
                display: inline-block;
                padding: 12px 16px;
                background: white;
                border-radius: 12px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }

            .typing-indicator span {
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #667eea;
                margin: 0 2px;
                animation: typing 1.4s infinite;
            }

            .typing-indicator span:nth-child(2) {
                animation-delay: 0.2s;
            }

            .typing-indicator span:nth-child(3) {
                animation-delay: 0.4s;
            }

            @keyframes typing {
                0%, 60%, 100% {
                    transform: translateY(0);
                }
                30% {
                    transform: translateY(-10px);
                }
            }
        </style>
    `;

    // Insert chatbot into page
    // Check if DOM is already loaded (script might load after DOMContentLoaded fires)
    function insertChatbot() {
        const chatbotDiv = document.getElementById('chatbot');
        if (chatbotDiv) {
            chatbotDiv.innerHTML = chatbotHTML;
            initializeChatbot();
        }
    }

    // If DOM is already loaded, execute immediately, otherwise wait for DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', insertChatbot);
    } else {
        // DOM is already loaded, execute immediately
        insertChatbot();
    }

    function initializeChatbot() {
        const toggle = document.getElementById('chatbot-toggle');
        const closeBtn = document.getElementById('chatbot-close');
        const window = document.getElementById('chatbot-window');
        const input = document.getElementById('chatbot-input');
        const sendBtn = document.getElementById('chatbot-send');
        const messagesContainer = document.getElementById('chatbot-messages');

        // Toggle chatbot window
        toggle.addEventListener('click', () => {
            if (window.style.display === 'none' || window.style.display === '') {
                window.style.display = 'flex';
                input.focus();
            } else {
                window.style.display = 'none';
            }
        });

        closeBtn.addEventListener('click', () => {
            window.style.display = 'none';
        });

        // Send message
        function sendMessage() {
            const message = input.value.trim();
            if (!message) return;

            // Add user message
            addMessage(message, 'user');
            input.value = '';

            // Show typing indicator
            const typingId = showTyping();

            // Send to backend
            fetch('/chatbot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message })
            })
                .then(response => response.json())
                .then(data => {
                    removeTyping(typingId);
                    if (data.response) {
                        addMessage(data.response, 'bot');
                    } else {
                        addMessage('Sorry, I encountered an error. Please try again.', 'bot');
                    }
                })
                .catch(error => {
                    removeTyping(typingId);
                    console.error('Error:', error);
                    addMessage('Sorry, I\'m having trouble connecting. Please check if the Gemini API key is configured.', 'bot');
                });
        }

        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });

        function addMessage(text, sender) {
            const messageDiv = document.createElement('div');
            messageDiv.style.cssText = `
                padding: 12px 16px;
                border-radius: 12px;
                margin-bottom: 12px;
                animation: slideIn 0.3s ease;
                max-width: 85%;
                word-wrap: break-word;
            `;

            if (sender === 'user') {
                messageDiv.style.cssText += `
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    margin-left: auto;
                    text-align: right;
                `;
                messageDiv.innerHTML = `<p style="margin: 0; line-height: 1.5;">${escapeHtml(text)}</p>`;
            } else {
                messageDiv.style.cssText += `
                    background: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                `;
                messageDiv.innerHTML = `
                    <strong style="color: #667eea;">🤖 AI Assistant</strong>
                    <p style="margin: 8px 0 0 0; color: #333; line-height: 1.5;">${formatBotMessage(text)}</p>
                `;
            }

            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        function showTyping() {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'typing-indicator';
            typingDiv.innerHTML = '<span></span><span></span><span></span>';
            typingDiv.id = 'typing-' + Date.now();
            messagesContainer.appendChild(typingDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            return typingDiv.id;
        }

        function removeTyping(id) {
            const typingDiv = document.getElementById(id);
            if (typingDiv) {
                typingDiv.remove();
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatBotMessage(text) {
            // Convert markdown-style formatting to HTML
            text = escapeHtml(text);
            text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
            text = text.replace(/\n/g, '<br>');
            return text;
        }
    }
})();
