# main_neural_train.py

import argparse
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras import regularizers
from tensorflow.keras.optimizers import Nadam
from tensorflow.keras.layers import LeakyReLU
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau


parser = argparse.ArgumentParser()
#parser.add_argument("--seed", "-s", type=int, default=None)
#parser.add_argument("--num-games", "-n", type=int, default=None)
#parser.add_argument("--verbose", "-v", action="store_true", help="Print every move")
parser.add_argument("--load-weights", "-L", action="store_true", help="Load weights into model")
parser.add_argument("--train", "-T", action="store_true", help="Perform model training")
parser.add_argument("--predict", "-p", type=int, help="Predict move #")
args = parser.parse_args()

# === Load CSV ===
print("Load CSV")
df = pd.read_csv("anty_training_data.csv")

# Check class distribution for each of the three targets
for col in ['Up1', 'Up2', 'Up3']:
    print(f"\nClass distribution for {col}:")
    print(df[col].value_counts(normalize=True))  # Use normalize=False to get absolute counts

# === Define known tickers ===
tickers = [
    "AUDNZD",
    "AUDUSD",
    "EURCHF",
    "EURUSD",
    "GBPJPY",
    "USDCAD",
    "XAUUSD",
    "XAGUSD"
]
#tickers = sorted(df['Ticker'].unique())  # or define manually
ticker_to_index = {t: i for i, t in enumerate(tickers)}
num_tickers = len(tickers)

# === One-hot encode tickers ===
def one_hot_encode_ticker(ticker):
    vec = np.zeros(num_tickers)
    vec[ticker_to_index[ticker]] = 1.0
    return vec

# === Process dataset ===
print("Process dataset")

input_length = 5
X = []
y = []

for _, row in df.iterrows():
    ticker_encoded = one_hot_encode_ticker(row['Ticker'])
    A_values = [row[f'A{i}'] for i in range(input_length)]
    B_values = [row[f'B{i}'] for i in range(input_length)]
    C_values = [row[f'C{i}'] for i in range(input_length)]
    inputs = np.concatenate([ticker_encoded, A_values, B_values, C_values])
    
    # Labels are in -1, 0, 1
    labels = [row['Up1'], row['Up2'], row['Up3']]
    
    X.append(inputs)
    y.append(labels)

X = np.array(X, dtype=np.float32)
y = np.array(y, dtype=np.int32)

# === Train/test split ===
print("Train/test split")

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Convert y into separate label arrays per output (not one-hot)
y_train_cat = [y_train[:, i] for i in range(3)]
y_test_cat = [y_test[:, i] for i in range(3)]

# === Define model ===
print("Define model")

input_dim = X.shape[1]
input_layer = layers.Input(shape=(input_dim,))

x = layers.Dense(64, kernel_regularizer=regularizers.l2(0.001))(input_layer)
x = layers.BatchNormalization()(x)
x = LeakyReLU()(x)
x = layers.Dropout(0.3)(x)

x = layers.Dense(64, kernel_regularizer=regularizers.l2(0.001))(x)
x = layers.BatchNormalization()(x)
x = LeakyReLU()(x)
x = layers.Dropout(0.3)(x)

out1 = layers.Dense(1, activation='sigmoid', name='Up1')(x)
out2 = layers.Dense(1, activation='sigmoid', name='Up2')(x)
out3 = layers.Dense(1, activation='sigmoid', name='Up3')(x)

model = models.Model(inputs=input_layer, outputs=[out1, out2, out3])

model.compile(optimizer=Nadam(learning_rate=0.001), 
              loss={'Up1': 'binary_crossentropy', 'Up2': 'binary_crossentropy', 'Up3': 'binary_crossentropy'},
              metrics={'Up1': 'accuracy', 'Up2': 'accuracy', 'Up3': 'accuracy'})

model.summary()

# === Callbacks ===
checkpoint_path = "anty.weights.h5"
cp_callback = tf.keras.callbacks.ModelCheckpoint(filepath=checkpoint_path, save_weights_only=True, verbose=1)
early_stopping = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
lr_scheduler = ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=3, verbose=1)

# === Load weights if requested ===
if args.load_weights:
    print(f"Load weights from {checkpoint_path}")
    model.load_weights(checkpoint_path)

# === Train the model ===
print("Train model")

model.fit(
    X_train,
    y_train_cat,
    validation_data=(X_test, y_test_cat),
    epochs=20,
    batch_size=32,
    callbacks=[cp_callback, early_stopping, lr_scheduler]
)

print("Evaluate model")
metrics = model.evaluate(X_test, y_test_cat, verbose=0)

# Define your metric names (as per your model)
metric_names = model.metrics_names

# Pretty print the results
print(f"\nModel Evaluation Results:")
for name, metric in zip(metric_names, metrics):
    print(f"{name}: {metric:.4f}")
