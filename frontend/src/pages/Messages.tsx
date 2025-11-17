import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { ConversationSummary, ConversationDetail } from '@/lib/types';
import { useAuthStore } from '@/lib/store';

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function ConversationList({
  conversations,
  selectedId,
  onSelect,
}: {
  conversations: ConversationSummary[];
  selectedId?: number;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="h-full flex flex-col">
      {conversations.map((conv) => (
        <button
          key={conv.id}
          onClick={() => onSelect(conv.id)}
          className={`p-4 border-b border-gray-800 text-left hover:bg-gray-800 transition-colors ${
            selectedId === conv.id ? 'bg-gray-800' : ''
          }`}
        >
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-owl-500 to-owl-600 flex items-center justify-center text-white font-semibold">
              {conv.other_participant.username[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <span className="font-semibold truncate">
                  {conv.other_participant.display_name || conv.other_participant.username}
                </span>
                {conv.last_message_at && (
                  <span className="text-xs text-gray-500">
                    {formatTimeAgo(conv.last_message_at)}
                  </span>
                )}
              </div>
              {conv.last_message && (
                <p className="text-sm text-gray-400 truncate">
                  {conv.last_message.content}
                </p>
              )}
              {conv.unread_count > 0 && (
                <div className="mt-1">
                  <span className="inline-block px-2 py-0.5 bg-owl-500 text-white text-xs rounded-full">
                    {conv.unread_count}
                  </span>
                </div>
              )}
            </div>
          </div>
        </button>
      ))}
      {conversations.length === 0 && (
        <div className="p-8 text-center text-gray-500">
          No conversations yet. Start a new message!
        </div>
      )}
    </div>
  );
}

function MessageThread({
  conversation,
  currentUserId,
  onSendMessage,
}: {
  conversation: ConversationDetail;
  currentUserId: number;
  onSendMessage: (content: string) => void;
}) {
  const [messageInput, setMessageInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation.messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (messageInput.trim()) {
      onSendMessage(messageInput.trim());
      setMessageInput('');
    }
  };

  const otherParticipant = conversation.participants.find(
    (p) => p.id !== currentUserId
  );

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-gray-800 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-owl-500 to-owl-600 flex items-center justify-center text-white font-semibold">
          {otherParticipant?.username[0].toUpperCase() || '?'}
        </div>
        <div>
          <div className="font-semibold">
            {otherParticipant?.display_name || otherParticipant?.username || 'Unknown'}
          </div>
          {otherParticipant?.username && (
            <div className="text-sm text-gray-500">@{otherParticipant.username}</div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {conversation.messages.map((message) => {
          const isSent = message.sender_id === currentUserId;
          return (
            <div
              key={message.id}
              className={`flex ${isSent ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-md px-4 py-2 rounded-lg ${
                  isSent
                    ? 'bg-owl-600 text-white'
                    : 'bg-gray-800 text-gray-100'
                }`}
              >
                <p className="whitespace-pre-wrap break-words">{message.content}</p>
                <div
                  className={`text-xs mt-1 ${
                    isSent ? 'text-owl-200' : 'text-gray-500'
                  }`}
                >
                  {formatTimeAgo(message.created_at)}
                </div>
              </div>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Message Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            type="text"
            value={messageInput}
            onChange={(e) => setMessageInput(e.target.value)}
            placeholder="Type a message..."
            className="flex-1 px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-owl-500"
          />
          <button
            type="submit"
            disabled={!messageInput.trim()}
            className="px-6 py-2 bg-owl-600 hover:bg-owl-700 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-lg font-semibold transition-colors"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

function NewConversationModal({
  onClose,
  onStart,
}: {
  onClose: () => void;
  onStart: (username: string) => void;
}) {
  const [username, setUsername] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.trim()) {
      onStart(username.trim());
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg p-6 w-full max-w-md">
        <h2 className="text-2xl font-bold mb-4">New Message</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username..."
              className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-owl-500"
              autoFocus
            />
          </div>
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!username.trim()}
              className="px-4 py-2 bg-owl-600 hover:bg-owl-700 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-lg font-semibold transition-colors"
            >
              Start Conversation
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Messages() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentConversation, setCurrentConversation] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNewConversation, setShowNewConversation] = useState(false);

  // Load conversations list
  useEffect(() => {
    loadConversations();
  }, []);

  // Load specific conversation when ID changes
  useEffect(() => {
    if (conversationId) {
      loadConversation(parseInt(conversationId));
    } else {
      setCurrentConversation(null);
    }
  }, [conversationId]);

  const loadConversations = async () => {
    try {
      setLoading(true);
      const data = await apiClient.listConversations();
      setConversations(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversations');
    } finally {
      setLoading(false);
    }
  };

  const loadConversation = async (id: number) => {
    try {
      const data = await apiClient.getConversation(id);
      setCurrentConversation(data);
      // Mark as read
      await apiClient.markConversationRead(id);
      // Refresh conversation list to update unread count
      loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversation');
    }
  };

  const handleSelectConversation = (id: number) => {
    navigate(`/messages/${id}`);
  };

  const handleSendMessage = async (content: string) => {
    if (!currentConversation) return;

    try {
      const newMessage = await apiClient.sendMessage(currentConversation.id, content);
      // Add message to current conversation
      setCurrentConversation({
        ...currentConversation,
        messages: [...currentConversation.messages, newMessage],
      });
      // Refresh conversations to update last message
      loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message');
    }
  };

  const handleStartConversation = async (username: string) => {
    try {
      const conversation = await apiClient.startConversation(username);
      setShowNewConversation(false);
      navigate(`/messages/${conversation.id}`);
      // Refresh conversations list
      loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start conversation');
    }
  };

  if (loading && conversations.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500">Loading messages...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {/* Conversations List */}
      <div className="w-80 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <h1 className="text-2xl font-bold">Messages</h1>
          <button
            onClick={() => setShowNewConversation(true)}
            className="px-3 py-1 bg-owl-600 hover:bg-owl-700 rounded-lg text-sm font-semibold transition-colors"
          >
            New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <ConversationList
            conversations={conversations}
            selectedId={conversationId ? parseInt(conversationId) : undefined}
            onSelect={handleSelectConversation}
          />
        </div>
      </div>

      {/* Message Thread */}
      <div className="flex-1 flex flex-col">
        {currentConversation && user ? (
          <MessageThread
            conversation={currentConversation}
            currentUserId={user.id}
            onSendMessage={handleSendMessage}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            {conversationId ? 'Loading conversation...' : 'Select a conversation to start messaging'}
          </div>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <div className="fixed bottom-4 right-4 bg-red-600 text-white px-4 py-2 rounded-lg shadow-lg">
          {error}
        </div>
      )}

      {/* New Conversation Modal */}
      {showNewConversation && (
        <NewConversationModal
          onClose={() => setShowNewConversation(false)}
          onStart={handleStartConversation}
        />
      )}
    </div>
  );
}
