import argparse
import os
import pandas as pd
from Neo4jGraphRAG import Neo4jGraphRAG

def setup_dataset(fallacy_set='logic',length=100):
    print(f"Setting up dataset for {fallacy_set}, size {length}")
    if fallacy_set=='logic':
        df_fallacies=pd.read_csv('data/fallacies.csv')
        df_fallacies['label']=[0]*len(df_fallacies)
        df_fallacies=df_fallacies[['source_article','label','updated_label']]
        df_fallacies=df_fallacies.sample(length,random_state=683)
    elif fallacy_set=='logicclimate':
        df_fallacies=pd.read_csv('data/fallacies_climate.csv')
        df_fallacies['label']=[0]*len(df_fallacies)
        df_fallacies=df_fallacies[['source_article','logical_fallacies','label']]
        df_fallacies=df_fallacies.sample(length,random_state=683)
    elif fallacy_set=='nli':
        df_fallacies=pd.read_csv('data/nli_fallacies_test.csv')
        df_fallacies['label']=[0]*len(df_fallacies)
        df_fallacies=df_fallacies[['sentence','label']]
        df_fallacies=df_fallacies.sample(length,random_state=683)
    df_valids=pd.read_csv('data/nli_entailments_test.csv')
    df_valids['label']=[1]*len(df_valids)
    df_valids=df_valids[['sentence','label']]
    df_valids=df_valids.sample(length,random_state=113)
    df = pd.concat([df_fallacies, df_valids])
    df = df.reset_index(drop=True)
    df['articles'] = df['source_article'].combine_first(df['sentence'])
    df = df.drop(['source_article', 'sentence'], axis=1)
    return df

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Neuro-Symbolic NL2FOL GraphRAG (Z3)")
    parser.add_argument('--run_name', type=str, required=True, help="Run name for saving results")
    parser.add_argument('--length', type=int, required=True, help="Length for dataset setup")
    parser.add_argument('--dataset', type=str, required=True, help="dataset for testing")
    args = parser.parse_args()

    df = setup_dataset(fallacy_set=args.dataset, length=args.length)
    df.to_csv('dataset.csv', index=False)

    rag = Neo4jGraphRAG(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
        mistral_api_key=os.getenv("MISTRAL_API_KEY", "")
    )

    results = []
    explanations = []

    for i, row in df.iterrows():
        print(f"Index {i}/{len(df)}")
        try:
            output_reason = rag.answer_query(row['articles'])
            classification = "Valid"
            if "Classification name" in output_reason or "Fallacy" in output_reason or "fallacy" in output_reason:
                classification = "LF"
            print(f"-> {classification}")
            results.append(classification)
            explanations.append(output_reason)
        except Exception as e:
            print(f"Error processing: {e}")
            results.append("LF") # Assume LF in case of error? Or we can just drop it.
            explanations.append(str(e))

    rag.close()

    df['result'] = results
    df['explanation'] = explanations
    
    os.makedirs('results', exist_ok=True)
    df.to_csv(f'results/{args.run_name}.csv', index=False)
    print(f"Done. Saved to results/{args.run_name}.csv")

