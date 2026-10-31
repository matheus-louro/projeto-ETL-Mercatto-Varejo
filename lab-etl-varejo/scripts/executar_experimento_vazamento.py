#!/usr/bin/env python3
"""
Execução e análise comparativa do experimento de vazamento de dados.
Gera métricas, matrizes de confusão, curvas ROC e gráficos comparativos.
"""
import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    roc_auc_score, balanced_accuracy_score, f1_score,
    precision_score, recall_score, confusion_matrix, roc_curve
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA_DIR = os.path.join(BASE_DIR, 'saida')
IMG_DIR = os.path.join(SAIDA_DIR, 'graficos_experimento')
os.makedirs(IMG_DIR, exist_ok=True)

CSV_CORRETA = os.path.join(SAIDA_DIR, 'abt_recompra_correta.csv')
CSV_VAZAMENTO = os.path.join(SAIDA_DIR, 'abt_recompra_vazamento.csv')

def carregar_dados(caminho):
    # Pula as duas linhas de metadados do Orange (tipos e papéis)
    df = pd.read_csv(caminho, skiprows=[1, 2])
    return df

def preparar_features(df):
    X = df.drop(columns=['cliente_sk', 'data_corte', 'alvo_recompra_90d']).copy()
    y = df['alvo_recompra_90d'].copy().astype(int)
    # Tratar nulos na nota média de avaliações (imputação com zero ou média)
    X['nota_media_avaliacoes'] = X['nota_media_avaliacoes'].fillna(0)
    X['sem_nota_avaliacao'] = X['sem_nota_avaliacao'].astype(int)
    return X, y

def avaliar_modelos(X, y, random_state=42):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.30, random_state=random_state, stratify=y
    )
    
    modelos = {
        'Naive Bayes': GaussianNB(),
        'Regressão Logística': LogisticRegression(max_iter=1000, random_state=random_state),
        'Árvore de Decisão': DecisionTreeClassifier(max_depth=5, random_state=random_state)
    }
    
    resultados = {}
    curvas = {}
    
    for nome, modelo in modelos.items():
        modelo.fit(X_train, y_train)
        y_pred = modelo.predict(X_test)
        y_prob = modelo.predict_proba(X_test)[:, 1]
        
        auc = roc_auc_score(y_test, y_prob)
        bal_acc = balanced_accuracy_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        cm = confusion_matrix(y_test, y_pred)
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        
        resultados[nome] = {
            'AUC': float(auc),
            'Acurácia Balanceada': float(bal_acc),
            'F1-Score': float(f1),
            'Precisão': float(prec),
            'Revocação': float(rec),
            'Matriz de Confusão': cm.tolist(),
            'TN': int(cm[0, 0]),
            'FP': int(cm[0, 1]),
            'FN': int(cm[1, 0]),
            'TP': int(cm[1, 1])
        }
        curvas[nome] = (fpr, tpr, auc)
        
    return resultados, curvas, X_test, y_test, modelos

def main():
    print("Carregando bases...")
    df_c = carregar_dados(CSV_CORRETA)
    df_v = carregar_dados(CSV_VAZAMENTO)
    
    # 1. Avaliação ABT Correta
    Xc, yc = preparar_features(df_c)
    res_c, curvas_c, X_test_c, y_test_c, mod_c = avaliar_modelos(Xc, yc)
    
    # 2. Avaliação ABT com Vazamento Sutil Apenas (Z-score global antes do split)
    df_sutil = df_c.copy()
    for col in ['valor_monetario_total', 'ticket_medio']:
        df_sutil[col] = (df_sutil[col] - df_sutil[col].mean()) / df_sutil[col].std()
    Xs, ys = preparar_features(df_sutil)
    res_s, curvas_s, _, _, _ = avaliar_modelos(Xs, ys)
    
    # 3. Avaliação ABT com Vazamento Completo (Temporal + Sutil)
    Xv, yv = preparar_features(df_v)
    res_v, curvas_v, X_test_v, y_test_v, mod_v = avaliar_modelos(Xv, yv)
    
    # Salvar resultados em JSON estruturado
    dados_consolidados = {
        'correta': res_c,
        'vazamento_sutil_apenas': res_s,
        'vazamento_completo': res_v
    }
    with open(os.path.join(SAIDA_DIR, 'semana4_metricas_experimento.json'), 'w', encoding='utf-8') as f:
        json.dump(dados_consolidados, f, indent=2, ensure_ascii=False)
        
    print("\n=== RESUMO DAS MÉTRICAS ===")
    for modelo in ['Naive Bayes', 'Regressão Logística', 'Árvore de Decisão']:
        print(f"\n[{modelo}]")
        print(f"  Correta:           AUC={res_c[modelo]['AUC']:.4f} | BalAcc={res_c[modelo]['Acurácia Balanceada']:.4f} | F1={res_c[modelo]['F1-Score']:.4f}")
        print(f"  Sutil (Z-score):   AUC={res_s[modelo]['AUC']:.4f} | BalAcc={res_s[modelo]['Acurácia Balanceada']:.4f} | F1={res_s[modelo]['F1-Score']:.4f}")
        print(f"  Vazamento Total:   AUC={res_v[modelo]['AUC']:.4f} | BalAcc={res_v[modelo]['Acurácia Balanceada']:.4f} | F1={res_v[modelo]['F1-Score']:.4f}")
        
    # --- GERAR GRÁFICOS ---
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    
    # 1. Curvas ROC Comparativas
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    cores = {'Naive Bayes': '#1f77b4', 'Regressão Logística': '#2ca02c', 'Árvore de Decisão': '#d62728'}
    
    # ROC Correta
    for nome, (fpr, tpr, auc) in curvas_c.items():
        axes[0].plot(fpr, tpr, label=f"{nome} (AUC = {auc:.3f})", color=cores[nome], lw=2)
    axes[0].plot([0, 1], [0, 1], 'k--', lw=1.5, alpha=0.7)
    axes[0].set_title("Curvas ROC — ABT Correta (Sem Vazamento)", fontsize=13, fontweight='bold')
    axes[0].set_xlabel("Taxa de Falsos Positivos (1 - Especificidade)", fontsize=11)
    axes[0].set_ylabel("Taxa de Verdadeiros Positivos (Sensibilidade)", fontsize=11)
    axes[0].legend(loc="lower right", frameon=True)
    axes[0].set_xlim([0, 1])
    axes[0].set_ylim([0, 1.02])
    
    # ROC Vazamento
    for nome, (fpr, tpr, auc) in curvas_v.items():
        axes[1].plot(fpr, tpr, label=f"{nome} (AUC = {auc:.3f})", color=cores[nome], lw=2)
    axes[1].plot([0, 1], [0, 1], 'k--', lw=1.5, alpha=0.7)
    axes[1].set_title("Curvas ROC — ABT com Vazamento (Temporal + Sutil)", fontsize=13, fontweight='bold')
    axes[1].set_xlabel("Taxa de Falsos Positivos (1 - Especificidade)", fontsize=11)
    axes[1].set_ylabel("Taxa de Verdadeiros Positivos (Sensibilidade)", fontsize=11)
    axes[1].legend(loc="lower right", frameon=True)
    axes[1].set_xlim([0, 1])
    axes[1].set_ylim([0, 1.02])
    
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, 'curvas_roc_comparacao.png'), dpi=300)
    plt.close()
    
    # 2. Gráfico de Barras: Comparativo de AUC e Acurácia Balanceada
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    modelos = ['Naive Bayes', 'Regressão Logística', 'Árvore de Decisão']
    x = np.arange(len(modelos))
    width = 0.35
    
    auc_c = [res_c[m]['AUC'] for m in modelos]
    auc_v = [res_v[m]['AUC'] for m in modelos]
    bacc_c = [res_c[m]['Acurácia Balanceada'] for m in modelos]
    bacc_v = [res_v[m]['Acurácia Balanceada'] for m in modelos]
    
    axes[0].bar(x - width/2, auc_c, width, label='Correta', color='#4575b4')
    axes[0].bar(x + width/2, auc_v, width, label='Com Vazamento', color='#d73027')
    axes[0].set_title('Comparativo de AUC-ROC', fontsize=13, fontweight='bold')
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(modelos, fontsize=11)
    axes[0].set_ylim([0, 1.1])
    axes[0].legend(frameon=True)
    for i in range(len(modelos)):
        axes[0].text(x[i] - width/2, auc_c[i] + 0.02, f"{auc_c[i]:.3f}", ha='center', fontsize=10)
        axes[0].text(x[i] + width/2, auc_v[i] + 0.02, f"{auc_v[i]:.3f}", ha='center', fontsize=10, fontweight='bold')
        
    axes[1].bar(x - width/2, bacc_c, width, label='Correta', color='#4575b4')
    axes[1].bar(x + width/2, bacc_v, width, label='Com Vazamento', color='#d73027')
    axes[1].set_title('Comparativo de Acurácia Balanceada', fontsize=13, fontweight='bold')
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(modelos, fontsize=11)
    axes[1].set_ylim([0, 1.1])
    axes[1].legend(frameon=True)
    for i in range(len(modelos)):
        axes[1].text(x[i] - width/2, bacc_c[i] + 0.02, f"{bacc_c[i]:.3f}", ha='center', fontsize=10)
        axes[1].text(x[i] + width/2, bacc_v[i] + 0.02, f"{bacc_v[i]:.3f}", ha='center', fontsize=10, fontweight='bold')
        
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, 'metricas_barras_comparacao.png'), dpi=300)
    plt.close()

    # 3. Distribuição de Recência (A Evidência do Crime!)
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.histplot(df_v['recencia_dias'], bins=60, color='#d73027', kde=False, ax=ax)
    ax.axvline(0, color='black', linestyle='--', linewidth=2, label='Data de Corte (0 dias)')
    ax.set_title('Distribuição de recencia_dias na ABT com Vazamento\n(Evidência Cabal: Valores Negativos de Recência)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Dias de Recência (relativo a 30/06/2025)', fontsize=11)
    ax.set_ylabel('Contagem de Clientes', fontsize=11)
    ax.legend(frameon=True)
    negativos = (df_v['recencia_dias'] < 0).sum()
    pct_neg = (negativos / len(df_v)) * 100
    ax.text(0.05, 0.85, f"Clientes com recência < 0:\n{negativos:,} ({pct_neg:.1f}%)", 
            transform=ax.transAxes, bbox=dict(boxstyle='round', facecolor='white', alpha=0.9), fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, 'distribuicao_recencia_vazamento.png'), dpi=300)
    plt.close()

    # 4. Importância de Variáveis na Árvore de Decisão
    dt_v = mod_v['Árvore de Decisão']
    importancias = dt_v.feature_importances_
    features = Xv.columns
    indices = np.argsort(importancias)[::-1]
    
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(range(len(indices)), importancias[indices][::-1], color='#d73027', align='center')
    ax.set_yticks(range(len(indices)))
    ax.set_yticklabels(features[indices][::-1], fontsize=10)
    ax.set_xlabel('Importância Relativa (Gini Importance)', fontsize=11)
    ax.set_title('Importância de Atributos na Árvore de Decisão (Versão com Vazamento)', fontsize=12, fontweight='bold')
    for i, idx in enumerate(indices[::-1]):
        val = importancias[idx]
        if val > 0.001:
            ax.text(val + 0.01, i, f"{val*100:.1f}%", va='center', fontsize=9, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, 'importancia_atributos_arvore.png'), dpi=300)
    plt.close()
    
    print("\nTodos os gráficos e métricas foram gerados com sucesso em:", IMG_DIR)

if __name__ == '__main__':
    main()
