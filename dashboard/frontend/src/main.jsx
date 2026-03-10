import React from 'react';
import ReactDOM from 'react-dom/client';
import { RecoilRoot } from 'recoil';
import { ChainlitAPI, ChainlitContext } from '@chainlit/react-client';
import App from './App';
import './index.css';

const defaultChainlitServer = `${window.location.protocol}//${window.location.hostname}:8000`;
const CHAINLIT_SERVER = import.meta.env.VITE_CHAINLIT_SERVER || defaultChainlitServer;
const apiClient = new ChainlitAPI(CHAINLIT_SERVER, 'webapp');

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <RecoilRoot>
            <ChainlitContext.Provider value={apiClient}>
                <App />
            </ChainlitContext.Provider>
        </RecoilRoot>
    </React.StrictMode>
);
