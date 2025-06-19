import os
import json
import sqlite3
from mcp.server.fastmcp import FastMCP
from anthropic import Anthropic
from dotenv import load_dotenv
import pandas as pd
from typing import Dict

# Load environment variables from .env file
load_dotenv()

# initialse MCP server
mcp = FastMCP(
    name="SQLQueryAgent",
)

# Initialize the Anthropic client
anthropic_client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),)

# --- Absolute Paths for Data Files ---
# This ensures the server can find the files regardless of how it's started.
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "electric_vehicle_data.db")
DATA_DICT_PATH = os.path.join(BASE_DIR, "data", "data_dictionary.csv")

# --- Helper Function ---
def get_data_dictionary_description():
    """
    Reads the data dictionary CSV and formats it into a string, grouped by table,
    to provide clear context to the AI about the entire database schema.
    """
    try:
        df = pd.read_csv(DATA_DICT_PATH)
       
        # Check if the required 'Table Name' column exists
        if 'Table Name' not in df.columns:
            return "Error: The data dictionary CSV is missing the required 'Table Name' column."

        description = "This is the data dictionary. It explains the columns for multiple tables in the database:\n"
       
        # Group the dataframe by the 'Table Name'
        for table_name, group in df.groupby('Table Name'):
            description += f"\n--- Table: {table_name} ---\n"
            # Iterate over each row in the group (i.e., each column for the current table)
            for _, row in group.iterrows():
                description += f"- Column '{row['Column Header']}' (also called '{row['Business Header']}'): {row['Definition']}. Example: {row['Example']}\n"
       
        return description
       
    except FileNotFoundError:
        return "Data dictionary file not found. I will proceed without it."
    except Exception as e:
        return f"Error reading data dictionary: {e}"
    
def _parse_llm_json_response(llm_text_response: str) -> Dict:
    """
    A robust helper function to extract a JSON object from an LLM text response.
    """
    try:
        #find the start and end of the JSON object
        start_index = llm_text_response.find("{")
        end_index = llm_text_response.rfind("}") + 1
        if start_index != -1 and end_index != 0:
            json_str = llm_text_response[start_index:end_index]
            # Parse the JSON string to ensure it's valid
            return json.loads(json_str)
    except json.JSONDecodeError as e:
        return {"error": f"JSON decoding error: {e}"}
    return {"error": "No valid JSON found in the response."}

def get_database_schema(db_path):

    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    #give a list of all tables in the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    table_names = [table[0] for table in tables]
    str_table_names = ", ".join(table_names)
    str_table_names = str_table_names.replace(" ", "")

    schema_description = f"Database schema contains the following tables: {str_table_names}. Each table contains various columns with specific data types."
    for table_name in table_names:
        # Get the column names and types for each table
        schema_description += f"\n\nTable: {table_name}\nColumns:\n"
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        for col in columns:
            column_name = col[1]
            column_type = col[2]
            schema_description += f"{column_name} ({column_type})\n"
    # Close the database connection
    conn.close()
    # Return the schema description
    return schema_description
# --- Tool 1: NER Generator ---
@mcp.tool()
def ner_generator_dynamic(question: str) -> str: #returns a JSON string
    """
    Analyzes a question to extract key entities (tables, columns, filters)
    needed to form a database query. Uses a data dictionary for context.
    """
    data_dictionary = get_data_dictionary_description()
    prompt = f"""
    You are a data analyst. Your job is to extract key entities from a user's question.
    Use the provided data dictionary to understand the columns.
    Get the correct table name, columns to select, and any filters needed.
    The data dictionary provides the structure and meaning of the database tables and columns.
    For example, if you thought 'Electric_Range' but the Data Dictionary says 'Electric Range', you must correct it to '"Electric Range"'
    Use the provided data dictionary to understand the columns and tables. ** The user might mention multiple tables (counties). **


    Data Dictionary:
    {data_dictionary}

    User Question: "{question}"

    Extract the necessary components to answer the question. It's okay if the question involves multiple tables. Your output MUST be a single JSON object with keys: "table", "columns_to_select", and "filters".
    - "table": The table name, which is always a county name (e.g., "King").
    - "columns_to_select": A list of columns the user wants to see.
    - "filters": A dictionary of filters to apply, where the key is the column name and value is the condition.

    """
    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        json_str = response.content[0].text
        parsed_dict = _parse_llm_json_response(json_str)
        return json.dumps(parsed_dict)
        
    except Exception as e:
        return json.dumps({"error": f"Error in ner_generator_dynamic: {e}"})
    
# --- Tool 2: Create SQL ---
@mcp.tool()
def create_sql(question: str, ner_dict: Dict) -> str:#returns a JSON string
    """
    Creates a full SQLite query by combining the user's question and the
    extracted entities from the ner_generator_dynamic tool.
    """
    ner_json = json.dumps(ner_dict, indent=2)
    prompt = f"""
    You are an expert SQLite developer. Create a single, valid SQLite query to answer the user's question.
    Understand the user's intent and the context provided by the extracted entities.
    The query may be complex, using window functions (like ROW_NUMBER(), PARTITION BY), subqueries, or other advanced features.

    User's Question: "{question}"
    Extracted Entities: {ner_json}

     *** IMPORTANT INSTRUCTIONS FOR MULTI-TABLE QUERIES *** - The user's database has a separate table for each county (e.g., 'King', 'Thurston', 'Clark'). 
     - All these tables have the exact same columns (e.g., "Make", "Base MSRP", etc.). 
     - If the user's question involves comparing or finding data in *multiple* tables (e.g., "in both Thurston and Clark"), you MUST use a JOIN or INTERSECT statement. 
     - The most common way to do this is to JOIN the tables on a common column, like "Make" or "VIN (1-10)". 
     
     Example Task: "Find makes in both Thurston and Clark." 
     Example Correct Query: SELECT T1."Make" FROM Thurston AS T1 INNER JOIN Clark AS T2 ON T1."Make" = T2."Make";


    Your output MUST be the raw SQLite query text, and nothing else. Do not wrap it in JSON or markdown.

    """
    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        
        # The raw SQL query is extracted from the response.
        raw_sql_query = response.content[0].text

        # We now reliably create the JSON object in Python.
        sql_dict = {"sql_query": raw_sql_query}
        
        return json.dumps(sql_dict)
    except Exception as e:
        return json.dumps({"error": f"LLM Error in create_sql: {e}"})



# --- Tool 3 : Validate SQL agent ---    
@mcp.tool()
def validator_sql_agent(question: str, ner_dict: Dict, generated_query_dict: Dict) -> str: #return a JSON string
    """
    Validates a generated SQL query for correctness, syntax, and hallucinations against the schema.
    Returns a corrected/validated version as a JSON string.
    """
    schema_info = get_database_schema(DB_PATH)
    generated_query_json = json.dumps(generated_query_dict) #here it converts the dict to a JSON string
    data_dictionary_info = get_data_dictionary_description()
    prompt = f"""
    You are an extreamely meticulous SQL validator and debugger. Your task is to check if the provided SQL query correctly answers the user's question and is syntactically correct for SQLite.
    You MUST Strictly follow the schema information provided to ensure no incorrect column or table names. Pay close attention to space or special characters in names. Column names with spaces must be enclosed in double quotes (e.g., "Electric Range").
    Avoid hallucinations or incorrect names.

    Provided Information:
    1.  User's Original Question: "{question}"
    2.  Extracted Entities (for context): {json.dumps(ner_dict, indent=2)}
    3.  Generated SQL Query to Validate: {generated_query_json}
    4.  *** Official Database Schema: *** {schema_info}
    5.  *** Data Dictionary: *** (for examples of values)
        {data_dictionary_info}

    Your Two Mandatory Tasks: 
    1. **Correct Column Names:** First, verify that every single column and table name in the query (in SELECT, WHERE, GROUP BY, etc.) exactly matches a name in the Official Schema. If you see a simplified name like `Make` or `Fuel_Type`, you MUST correct it to the full, quoted name like `"Make"` or `"Electric Vehicle Type"`. 
    2. **Correct Column Values:** Second, for any columns being filtered in the WHERE clause (like "Electric Vehicle Type"), you MUST ensure the values being compared match the examples in the Data Dictionary. For example, if the query says `... = 'BEV'`, you MUST correct it to `... = 'Battery Electric Vehicle (BEV)'`.

    Your Important Tasks to follow:
    1. *** CRITICAL VALIDATION: *** Go through every column in the SELECT, WHERE, GROUP BY, and ORDER BY clauses of the generated query. Compare each one against the column names listed in the Official Database Schema.
    2. If a column name like `VIN` or `MSRP` is used, but the schema specifies `"VIN (1-10)"` or `"Base MSRP"`, you MUST replace it with the correct, fully quoted name from the schema. There are no exceptions.
    3. Correct any incorrect column/table names using the Official Schema. Remember to quote names with spaces (e.g., "Electric Vehicle Type")
    4. *** CRITICAL LOGIC CHECK: *** For categorical columns like "Electric Vehicle Type", the WHERE clause must use the full value found in the data dictionary examples (e.g., 'Battery Electric Vehicle (BEV)'), not just an acronym (e.g., 'BEV'). Check the generated query and correct it if necessary.
    5.  Check for "hallucinated" or incorrect column and table names by comparing against the official schema. For example, if you see 'Electric_Range' but the schema says 'Electric Range', you must correct it to '"Electric Range"'
    6.  Ensure the query logic accurately reflects the user's question (e.g., if they ask for "top 3", there should be an ORDER BY and LIMIT 3).

 
    
    Your output MUST be a single JSON object with one key: "sql_query", containing the final, validated, and potentially corrected query.
    """
    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[{"role": "user", "content": prompt}]
        )
        parsed_dict = _parse_llm_json_response(response.content[0].text)
        return json.dumps(parsed_dict)
    except Exception as e:
        return json.dumps({"error": f"LLM Error in validator_sql_agent: {e}"})

# --- Tool 4: Run SQLite Query---
@mcp.tool()
def run_sqlite_query(sql_dict: Dict) -> str:  #returns a JSON string
    """Executes a SQL query and returns the data as a JSON string."""
    try:
        #json_str = sql_json[sql_json.find('{') : sql_json.rfind('}') + 1]
        sql_query = sql_dict.get("sql_query")
        # data = json.loads(json_str)
        # sql_query = data.get("sql_query")

        # if data.get("error"):
        #     return json.dumps({"error": f"Cannot execute due to previous error: {data['error']}", "data": []})
        if not sql_query:
            return json.dumps({"error": "No SQL query provided.", "data": []})

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        results = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]
        conn.close()

        formatted_results = [dict(zip(column_names, row)) for row in results]
        return json.dumps({"data": formatted_results})
        # print(f"Query executed successfully. Results: {formatted_results}")
        # return {"data": formatted_results}
      
    except Exception as e:
        return json.dumps({"error": f"Database query failed: {e}", "data": []})

# --- Tool 5: Handle Error Agent (NEW) ---
@mcp.tool()
def handle_error_agent(failed_sql_query_dict: Dict, error_message: str) -> str: #returns a JSON string
    """
    Attempts to fix a failed SQL query based on the specific error message from the database.
    """
    failed_sql_query = failed_sql_query_dict.get("sql_query", "Query not provided")
    prompt = f"""
    You are a highly skilled SQLite expert debugging a query.
    
    The following SQL query failed to execute:
    ```sql
    {failed_sql_query}
    ```

    It produced this specific error message:
    `{error_message}`

    Task:
    1.  Carefully analyze the query and the error message.
    2.  Provide a corrected SQLite query that resolves the identified error.
    
    Your output MUST be a single JSON object with one key: "sql_query", containing only the corrected query.
    """
    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[{"role": "user", "content": prompt}]
        )
        parsed_dict = _parse_llm_json_response(response.content[0].text)

        return json.dumps(parsed_dict)
    except Exception as e:
        return json.dumps({"error": f"LLM Error in handle_error_agent: {e}"})

# --- Tool 6: Generate Final Answer ---
@mcp.tool()
def generate_final_answer(question: str, query_result_dict: Dict) -> str:
    """Takes the database results and generates a human-readable answer."""
    query_result_json = json.dumps(query_result_dict, indent=2) 

    prompt = f"""
    You are a helpful assistant. Answer the user's question based on the provided data.
    If the data contains an error, explain it simply. If the data is empty, say so.
   

    Original Question: "{question}"
    Data from Database: {query_result_json}

    Instructions:
    1. Provide a direct, clear answer without using phrases like "Based on the provided data" or "According to the context"
    2. Use simple, non-technical language
    3. Keep the response concise and to the point
    4. If you don't have enough information to answer, simply say "I'm sorry, I don't have enough information to answer that question"
    """
    try:
        response = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        print(f"Final Answer Result: {response.content[0].text}")
        return response.content[0].text
    except Exception as e:
        return f"Error formulating final answer: {e}"

# --- Run Server ---
if __name__ == "__main__":
    print("MCP server with multi-step AI pipeline is starting...")
    mcp.run(transport="stdio")