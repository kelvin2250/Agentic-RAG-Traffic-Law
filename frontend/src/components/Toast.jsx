import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { X, AlertCircle, CheckCircle, Info, Loader } from 'lucide-react';
import styles from './Toast.module.css';

const ToastContext = createContext(null);

export function useToast() {
    return useContext(ToastContext);
}

function ToastItem({ id, type, message, onDismiss }) {
    useEffect(() => {
        if (type === 'loading') return;
        const timer = setTimeout(() => onDismiss(id), 4000);
        return () => clearTimeout(timer);
    }, [id, type, onDismiss]);

    const iconMap = {
        success: <CheckCircle size={16} />,
        error: <AlertCircle size={16} />,
        info: <Info size={16} />,
        loading: <Loader size={16} className={styles.spin} />,
    };

    return (
        <div className={`${styles.toast} ${styles[type]}`}>
            <span className={styles.icon}>{iconMap[type]}</span>
            <span className={styles.message}>{message}</span>
            {type !== 'loading' && (
                <button className={styles.close} onClick={() => onDismiss(id)}>
                    <X size={12} />
                </button>
            )}
        </div>
    );
}

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([]);

    const addToast = useCallback((type, message) => {
        const id = Date.now() + Math.random();
        setToasts(prev => [...prev, { id, type, message }]);
        return id;
    }, []);

    const dismissToast = useCallback((id) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    }, []);

    const toast = {
        success: (msg) => addToast('success', msg),
        error: (msg) => addToast('error', msg),
        info: (msg) => addToast('info', msg),
        loading: (msg) => addToast('loading', msg),
        dismiss: dismissToast,
    };

    return (
        <ToastContext.Provider value={toast}>
            {children}
            <div className={styles.container}>
                {toasts.map(t => (
                    <ToastItem key={t.id} {...t} onDismiss={dismissToast} />
                ))}
            </div>
        </ToastContext.Provider>
    );
}
