import React, { useState } from 'react';
import { Menu, Plus, Trash2, LogOut, MessageSquare, ChevronLeft, ChevronRight } from 'lucide-react';
import { authService } from '../services/auth';
import { useNavigate } from 'react-router-dom';
import styles from './Sidebar.module.css';

export default function Sidebar({ sessions, activeSessionId, onSelectSession, onCreateSession, onDeleteSession, isLoading }) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const userEmail = localStorage.getItem('user_email') || 'User';
  const navigate = useNavigate();

  const handleLogout = () => {
    authService.logout();
    navigate('/login');
  };

  return (
    <div className={`${styles.sidebar} ${isCollapsed ? styles.collapsed : ''}`}>
      <div className={styles.header}>
        {!isCollapsed && (
          <div className={styles.brand}>
            <span className={styles.logoIcon}>⚖️</span>
            <span className={styles.brandName}>Traffic Law</span>
          </div>
        )}
        <button
          className={styles.toggleBtn}
          onClick={() => setIsCollapsed(!isCollapsed)}
          title={isCollapsed ? "Mở rộng sidebar" : "Thu gọn sidebar"}
        >
          {isCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      <button
        className={styles.newChatBtn}
        onClick={onCreateSession}
        title="Cuộc trò chuyện mới"
      >
        <Plus size={20} />
        {!isCollapsed && <span>Cuộc trò chuyện mới</span>}
      </button>

      <div className={styles.historyList}>
        {!isCollapsed && <h3 className={styles.sectionTitle}>Gần đây</h3>}
        {isLoading ? (
          <>
            <div className={styles.skeletonItem} />
            <div className={styles.skeletonItem} />
            <div className={styles.skeletonItemShort} />
          </>
        ) : sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          return (
            <div
              key={session.id}
              className={`${styles.sessionItem} ${isActive ? styles.active : ''}`}
              onClick={() => onSelectSession(session.id)}
              title={session.title}
            >
              <MessageSquare size={16} className={styles.chatIcon} />
              {!isCollapsed && (
                <>
                  <span className={styles.titleText}>{session.title}</span>
                  <button
                    className={styles.deleteBtn}
                    onClick={(e) => onDeleteSession(session.id, e)}
                    title="Xóa cuộc trò chuyện"
                  >
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className={styles.footer}>
        {!isCollapsed ? (
          <div className={styles.userInfo}>
            <div className={styles.avatar}>
              {userEmail[0].toUpperCase()}
            </div>
            <div className={styles.userMeta}>
              <span className={styles.email} title={userEmail}>{userEmail}</span>
            </div>
            <button className={styles.logoutBtn} onClick={handleLogout} title="Đăng xuất">
              <LogOut size={16} />
            </button>
          </div>
        ) : (
          <button className={styles.logoutBtnCollapsed} onClick={handleLogout} title="Đăng xuất">
            <LogOut size={18} />
          </button>
        )}
      </div>
    </div>
  );
}
