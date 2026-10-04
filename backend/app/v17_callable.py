"""Generated frozen inference extraction. See scripts/extract_v17.py.
Original source SHA-256: afc2fb4b771467e3a47045b1c3b76f9dc898716078fc47d8f930bfb5093088d3
"""
from random import Random
import pandas as pd
import numpy as np

CATEGORICAL_COLS = ['Disease', 'Symptom Severity', 'Nadi Reading', 'Constitution/Prakriti', 'Stress Levels', 'Sleep Patterns', 'Age Group', 'Physical Activity Levels']
NUMERIC_COLS = ['BP Systolic', 'BP Diastolic', 'Pulse Rate', 'Weight (kg)']
INPUT_FEATURES = CATEGORICAL_COLS + NUMERIC_COLS
OUTPUT_TARGETS = ['Herbal Therapy Strategy', 'Lifestyle Recommendations', 'Therapeutic Yoga Module', 'Follow-up Recommendation']
LIFESTYLE_ACTIONS: dict = {'Stress Reduction Lifestyle': {'focus': 'Mental wellness and nervous system regulation', 'daily_habits': ['Practice 20 minutes of mindfulness or guided meditation each morning', 'Limit caffeine intake to 1 cup before noon', 'Maintain a consistent sleep-wake schedule (same time ±30 min daily)', 'Take 5-minute breathing breaks every 2 hours during work', 'Reduce screen exposure 1 hour before bedtime'], 'dietary_changes': ['Include Ashwagandha warm milk (1 tsp) before bed', 'Avoid highly processed foods and refined sugars', 'Eat warm, easily digestible meals — favour cooked over raw', 'Include magnesium-rich foods: spinach, almonds, pumpkin seeds'], 'wellness_tips': ['Journal thoughts each night for 5 minutes to offload mental load', 'Walk barefoot on grass (Earthing) for 10 minutes daily', 'Maintain regular social connections — isolation amplifies stress'], 'avoid': ['Late-night work', 'High-intensity competitive exercise', 'Irregular meal timing']}, 'Weight Management Lifestyle': {'focus': 'Metabolic regulation and sustainable body composition', 'daily_habits': ['Walk briskly for minimum 30 minutes after the largest meal of the day', 'Use smaller plates to reduce portion size without calorie counting', 'Drink 300 ml warm water 20 minutes before each meal', 'Weigh yourself weekly (not daily) to track trend without anxiety', 'Sleep 7–8 hours — sleep deprivation raises ghrelin (hunger hormone)'], 'dietary_changes': ['Adopt Ayurvedic principle: breakfast moderate, lunch largest, dinner lightest', 'Replace refined carbs with millets (ragi, jowar, bajra)', 'Include bitter gourd (karela) juice 30 ml on empty stomach 3×/week', 'Limit fried and deep-fat foods; use cold-pressed oils sparingly', 'Include fenugreek seeds (1 tsp soaked overnight) before breakfast'], 'wellness_tips': ['Track food intake in a simple diary for the first 2 weeks', 'Celebrate non-scale victories: energy, mood, clothing fit', 'Involve a family member in healthy cooking for accountability'], 'avoid': ['Crash diets', 'Skipping meals', 'Late-night heavy dinners', 'Sugary beverages']}, 'Sleep Improvement Lifestyle': {'focus': 'Circadian rhythm restoration and deep sleep quality', 'daily_habits': ['Go to bed and wake at the same time every day — weekends included', 'Keep bedroom cool (18–20°C), dark, and quiet', 'Avoid napping after 3 PM', 'No caffeine or alcohol within 6 hours of bedtime', 'Do light stretching or legs-up-the-wall pose for 10 min before bed'], 'dietary_changes': ['Drink warm turmeric milk (Haldi doodh) 30 minutes before sleep', 'Light dinner before 7:30 PM — avoid heavy proteins at night', 'Include tart cherry juice or banana for natural melatonin', 'Avoid spicy food at dinner — increases body temperature'], 'wellness_tips': ['Create a 30-minute pre-sleep ritual: dim lights, read, warm bath', 'Use progressive muscle relaxation if racing thoughts prevent sleep', 'Blue-light blocking glasses after 8 PM significantly improve sleep onset'], 'avoid': ['Screen time in bed', 'Heavy exercise after 7 PM', 'Stimulating conversations late at night']}, 'Active Lifestyle Promotion': {'focus': 'Building sustainable physical activity from a sedentary baseline', 'daily_habits': ['Start with 15-minute morning walks; increase 5 minutes each week', 'Use stairs instead of lifts for the first 3 floors', 'Set a phone reminder to stand and move for 2 minutes every hour', 'Aim for 7,000–10,000 steps per day as a progressive target', 'Exercise with a partner or group for accountability and motivation'], 'dietary_changes': ['Increase protein intake to support muscle building: eggs, legumes, paneer', 'Eat a banana or dates 30 minutes before exercise for natural energy', 'Stay hydrated: 250 ml water for every 20 minutes of activity', 'Post-exercise recovery: coconut water + a handful of nuts'], 'wellness_tips': ['Track activity with a simple step counter — visibility drives behaviour', 'Pick activities you enjoy: dancing, cycling, swimming, cricket', 'Rest 1 day per week to allow muscle repair'], 'avoid': ['Going from zero to intense exercise immediately', 'Skipping warm-up and cool-down', 'Dehydration during activity']}, 'Preventive Wellness Lifestyle': {'focus': 'Maintaining current health and building long-term resilience', 'daily_habits': ['Follow Dinacharya (Ayurvedic daily routine): wake before sunrise, tongue scrape, oil pulling', 'Practice Abhyanga (self-massage with sesame oil) 2–3 times per week', 'Maintain regular meal timings — eat at similar times each day', 'Annual full-body health check-up including blood panel', '30 minutes of moderate exercise 5 days per week'], 'dietary_changes': ['Eat seasonal, locally grown produce — aligned with your Prakriti', 'Include Triphala churna (1/2 tsp with warm water at bedtime) for gut health', 'Minimize processed and packaged foods', 'Practice mindful eating — chew each bite 20–30 times'], 'wellness_tips': ['Cultivate a gratitude practice: 3 things daily', 'Maintain social and creative hobbies for mental longevity', 'Sun exposure (15 min before 10 AM) for natural Vitamin D'], 'avoid': ['Ignoring early warning signs', 'Skipping annual health checks', 'Chronic sleep debt']}}
YOGA_MODULES: dict = {'Stress Reduction Yoga': {'focus': 'Calming the nervous system and releasing mental tension', 'duration': '30–45 minutes daily', 'poses': ["Balasana (Child's Pose) — 2 min, grounding and surrender", 'Viparita Karani (Legs-Up-Wall) — 5 min, parasympathetic activation', 'Uttanasana (Standing Forward Fold) — 1 min, brain blood flow', 'Janu Sirsasana (Head-to-Knee Forward Bend) — 1 min each side', 'Savasana (Corpse Pose) — 10 min, full body surrender'], 'pranayama': ['Nadi Shodhana (Alternate Nostril Breathing) — 10 min: balances left/right brain hemispheres', 'Bhramari (Humming Bee Breath) — 5 min: activates vagus nerve, instant calm', '4-7-8 Breathing — 4 min: inhale 4s, hold 7s, exhale 8s; slows heart rate'], 'meditation': 'Body Scan Meditation — 10 min before sleep', 'benefits': ['Reduces cortisol 20–30%', 'Improves sleep quality', 'Lowers blood pressure', 'Reduces anxiety and rumination'], 'precautions': ['Avoid inverted poses if hypertensive (BP > 160)', 'Stop if dizziness occurs during pranayama']}, 'Respiratory Pranayama': {'focus': 'Strengthening lung capacity and clearing respiratory pathways', 'duration': '25–35 minutes daily', 'poses': ['Gomukhasana (Cow-Face Pose) — opens chest and shoulders', 'Matsyasana (Fish Pose) — expands thoracic cavity', 'Setu Bandhasana (Bridge Pose) — strengthens diaphragm', 'Bhujangasana (Cobra Pose) — opens lungs, strengthens back', 'Trikonasana (Triangle Pose) — lateral chest expansion'], 'pranayama': ['Kapalbhati (Skull-Shining Breath) — 5 min: clears airways, expels CO₂', 'Bhastrika (Bellows Breath) — 3 min: maximum lung capacity exercise', 'Anulom Vilom (Alternate Nostril) — 10 min: balances respiratory rhythm', 'Ujjayi (Ocean Breath) — 5 min: warms airways, improves breath control'], 'meditation': 'Mindful breathing observation — 5 min', 'benefits': ['Increases vital lung capacity', 'Reduces asthma attacks', 'Improves oxygen saturation', 'Clears mucus and congestion'], 'precautions': ['Avoid Kapalbhati during acute asthma or fever', 'Practise Bhastrika only with trained guidance initially', 'Avoid retention (Kumbhaka) if hypertensive']}, 'Weight Management Yoga': {'focus': 'Boosting metabolism and building core strength', 'duration': '45–60 minutes daily', 'poses': ['Surya Namaskar (Sun Salutation) — 12 rounds: full-body warm-up + cardio', 'Virabhadrasana I & II (Warrior I & II) — 1 min each: builds leg and core strength', 'Navasana (Boat Pose) — 30 sec × 3: intense core activation', 'Ardha Chandrasana (Half Moon Pose) — balance and hip strengthening', 'Parivrtta Trikonasana (Revolved Triangle) — abdominal twist, digestive stimulation', 'Dhanurasana (Bow Pose) — stimulates digestive organs'], 'pranayama': ['Kapalbhati — 10 min: stimulates abdominal muscles and digestive fire (Agni)', 'Bhastrika — 5 min: raises metabolic rate', 'Surya Bhedana (Right Nostril Breathing) — 5 min: activates sympathetic metabolism'], 'meditation': 'Mindful eating visualization — 5 min before main meal', 'benefits': ['Boosts basal metabolic rate', 'Reduces visceral fat', 'Improves insulin sensitivity', 'Strengthens core and postural muscles'], 'precautions': ['Avoid Navasana if lower back pain is acute', 'Progress Surya Namaskar rounds gradually (start with 4)', 'Stay hydrated throughout session']}, 'Flexibility & Mobility Therapy': {'focus': 'Joint lubrication, range of motion, and pain relief', 'duration': '30–40 minutes daily', 'poses': ["Balasana (Child's Pose) — 3 min: lumbar decompression", 'Supta Kapotasana (Reclined Pigeon) — 2 min each: hip flexor release', 'Setu Bandhasana (Bridge Pose) — 1 min × 3: strengthens posterior chain', 'Pavanamuktasana (Wind-Relieving Pose) — releases lower back tension', 'Trikonasana (Triangle Pose) — lateral spine and hip stretch', 'Vakrasana (Spinal Twist) — lubricates intervertebral discs'], 'pranayama': ['Nadi Shodhana — 8 min: reduces systemic inflammation (parasympathetic)', 'Bhramari — 5 min: reduces pain perception via vagal tone'], 'meditation': 'Body awareness scan focusing on tense areas — 8 min', 'benefits': ['Reduces joint stiffness by 40–50%', 'Improves synovial fluid circulation', 'Reduces arthritis pain', 'Prevents injury and muscle imbalances'], 'precautions': ['Avoid deep twists in acute disc herniation', 'Use props (blocks, bolsters) generously', 'Never force a joint past pain threshold']}, 'Relaxation & Sleep Therapy': {'focus': 'Deep nervous system restoration and sleep onset support', 'duration': '30 minutes (ideally 8–9 PM)', 'poses': ['Viparita Karani (Legs-Up-Wall) — 10 min: reverses venous pooling, deep calm', 'Supta Baddha Konasana (Reclined Butterfly) — 5 min: hip release', 'Paschimottanasana (Seated Forward Fold) — 3 min: calms nervous system', "Balasana (Child's Pose) — 3 min: grounding, inward focus", 'Savasana with guided body scan — 10 min: full physical and mental release'], 'pranayama': ['Chandra Bhedana (Left Nostril Breathing) — 8 min: activates rest-digest mode', '4-7-8 Breathing — 5 min: proven sleep onset technique', 'Bhramari — 5 min: immediate nervous system deceleration'], 'meditation': 'Yoga Nidra (psychic sleep) — 20 min audio-guided', 'benefits': ['Improves sleep onset by 15–20 min', 'Increases deep NREM sleep proportion', 'Reduces nighttime cortisol', 'Addresses insomnia and fatigue'], 'precautions': ['Do not practice after heavy meals (wait 2 hours)', 'Avoid stimulating backbends close to bedtime', 'Use an eye pillow in Savasana for deeper relaxation']}}

def predict_single(bundle: dict, input_data: dict) -> dict:
    """
    Runs inference for a single patient and returns a structured prediction.

    Parameters
    ----------
    bundle     : loaded joblib bundle from ayursage_model.pkl
    input_data : dict with 12 input feature keys

    Returns
    -------
    dict with keys:
        'Herbal Therapy Strategy'       : dict  (ML label + AI reasoning)
        'Lifestyle Recommendations'     : dict  (category + actions + AI reasoning)
        'Therapeutic Yoga Module'       : dict  (category + poses + AI reasoning)
        'Follow-up Recommendation'      : dict  (ML label + AI reasoning)
        'Doctor Prescription & Care Notes' : str  (HITL placeholder — NOT ML)

    Flask app.py receives this dict and renders each section in the UI.
    The doctor then fills in 'Doctor Prescription & Care Notes' manually.
    """
    row = {f: input_data.get(f, 'Unknown') for f in bundle['input_features']}
    X_new = pd.DataFrame([row])
    for c in bundle['numeric_cols']:
        X_new[c] = pd.to_numeric(X_new[c], errors='coerce').fillna(0.0)
    X_pre = bundle['shared_pre'].transform(X_new)
    winner = bundle['best_overall_model']
    raw_labels = {}
    confidence_info = {}
    for i, col in enumerate(bundle['output_targets']):
        clf = bundle['models'][col][winner]
        pred_int = int(np.asarray(clf.predict(X_pre)).reshape(-1)[0])
        raw_labels[col] = bundle['le_output'][col].inverse_transform([pred_int])[0]
        if hasattr(clf, 'predict_proba'):
            try:
                proba_row = np.asarray(clf.predict_proba(X_pre)).reshape(-1)
                class_names = bundle['le_output'][col].classes_
                confidence_info[col] = {'confidence_score': round(float(proba_row[pred_int]), 4), 'class_probabilities': {str(class_names[j]): round(float(proba_row[j]), 4) for j in range(len(class_names))}}
            except Exception:
                confidence_info[col] = None
        else:
            confidence_info[col] = None
    lifestyle_cat = raw_labels.get('Lifestyle Recommendations', 'Preventive Wellness Lifestyle')
    yoga_cat = raw_labels.get('Therapeutic Yoga Module', 'Stress Reduction Yoga')
    herbal_cat = raw_labels.get('Herbal Therapy Strategy', 'Metabolic Balance Support')
    followup_cat = raw_labels.get('Follow-up Recommendation', 'Regular Wellness Follow-up')
    lifestyle_detail = bundle.get('lifestyle_engine', LIFESTYLE_ACTIONS).get(lifestyle_cat, {'category': lifestyle_cat, 'note': 'Details not available — consult doctor'})
    yoga_detail = bundle.get('yoga_engine', YOGA_MODULES).get(yoga_cat, {'category': yoga_cat, 'note': 'Details not available — consult doctor'})
    reasoning = generate_clinical_reasoning(input_data, raw_labels)
    result = {'Herbal Therapy Strategy': {'category': herbal_cat, 'reasoning': reasoning['herbal'], 'confidence': confidence_info.get('Herbal Therapy Strategy')}, 'Lifestyle Recommendations': {'category': lifestyle_cat, 'focus': lifestyle_detail.get('focus', ''), 'actions': lifestyle_detail.get('daily_habits', []), 'dietary_changes': lifestyle_detail.get('dietary_changes', []), 'wellness_tips': lifestyle_detail.get('wellness_tips', []), 'avoid': lifestyle_detail.get('avoid', []), 'reasoning': reasoning['lifestyle'], 'confidence': confidence_info.get('Lifestyle Recommendations')}, 'Therapeutic Yoga Module': {'category': yoga_cat, 'focus': yoga_detail.get('focus', ''), 'duration': yoga_detail.get('duration', ''), 'poses': yoga_detail.get('poses', []), 'pranayama': yoga_detail.get('pranayama', []), 'meditation': yoga_detail.get('meditation', ''), 'benefits': yoga_detail.get('benefits', []), 'precautions': yoga_detail.get('precautions', []), 'reasoning': reasoning['yoga'], 'confidence': confidence_info.get('Therapeutic Yoga Module')}, 'Follow-up Recommendation': {'category': followup_cat, 'reasoning': reasoning['followup'], 'confidence': confidence_info.get('Follow-up Recommendation')}, 'Doctor Prescription & Care Notes': 'PENDING_DOCTOR_REVIEW'}
    return result

def _patient_seed(input_data: dict) -> int:
    """
    Derive a stable per-patient integer seed for controlled language variation.
    Same patient inputs → same seed → same explanation phrasing (reproducible).
    Different patients → different seeds → naturally varied explanations.
    Uses djb2 hash on concatenated feature string (process-stable, no PYTHONHASHSEED).
    """
    seed_str = ''.join([str(input_data.get('Disease', '')), str(input_data.get('Stress Levels', '')), str(input_data.get('Sleep Patterns', '')), str(input_data.get('Constitution/Prakriti', '')), str(input_data.get('Nadi Reading', '')), str(input_data.get('BP Systolic', '')), str(input_data.get('Weight (kg)', '')), str(input_data.get('Physical Activity Levels', ''))])
    h = 5381
    for c in seed_str:
        h = (h << 5) + h + ord(c)
    return h & 2147483647

def _extract_wellness_factors(input_data: dict) -> dict:
    """
    Extract human-readable contributing wellness factors from patient features.

    Returns a dict of factor lists keyed by clinical domain:
      'metabolic'      — BP, weight, diabetes, activity
      'stress_sleep'   — stress levels, sleep patterns
      'constitution'   — Prakriti and Nadi reading
      'severity'       — symptom severity
      'joint'          — joint/inflammatory indicators from disease name
      'immune'         — fatigue/immunity indicators
      'digestive'      — gut/digestive indicators
      'respiratory'    — respiratory indicators

    Each list contains natural-language phrases ready for sentence insertion.
    These are dynamically composed from actual input values — not pre-written
    for specific patients.
    """
    d = input_data
    disease = str(d.get('Disease', '')).lower()
    stress = str(d.get('Stress Levels', '')).lower()
    sleep_p = str(d.get('Sleep Patterns', '')).lower()
    activity = str(d.get('Physical Activity Levels', '')).lower()
    prakriti = str(d.get('Constitution/Prakriti', '')).lower()
    nadi = str(d.get('Nadi Reading', '')).lower()
    severity = str(d.get('Symptom Severity', '')).lower()
    age = str(d.get('Age Group', '')).lower()
    try:
        bp_s = float(d.get('BP Systolic', 120))
    except:
        bp_s = 120.0
    try:
        bp_d = float(d.get('BP Diastolic', 80))
    except:
        bp_d = 80.0
    try:
        wt = float(d.get('Weight (kg)', 70))
    except:
        wt = 70.0
    try:
        pr = float(d.get('Pulse Rate', 75))
    except:
        pr = 75.0
    factors = {'metabolic': [], 'stress_sleep': [], 'constitution': [], 'severity': [], 'joint': [], 'immune': [], 'digestive': [], 'respiratory': []}
    if bp_s >= 160 or bp_d >= 100:
        factors['metabolic'].append('critically elevated blood pressure')
    elif bp_s >= 140 or bp_d >= 90:
        factors['metabolic'].append('elevated blood pressure (Stage 1 hypertension)')
    elif bp_s >= 130 or bp_d >= 85:
        factors['metabolic'].append('mildly elevated blood pressure')
    if wt >= 95:
        factors['metabolic'].append('significant weight excess (obesity range)')
    elif wt >= 80:
        factors['metabolic'].append('above-optimal body weight')
    if 'low' in activity:
        factors['metabolic'].append('a sedentary physical activity pattern')
    elif 'moderate' in activity:
        factors['metabolic'].append('a moderately active lifestyle')
    if pr >= 100:
        factors['metabolic'].append('elevated resting pulse rate')
    for kw, phrase in [('diabetes', 'insulin regulation concerns'), ('obesity', 'weight management challenges'), ('hypothyroid', 'thyroid function imbalance'), ('hyperlipid', 'lipid profile irregularities'), ('hypertension', 'persistent hypertensive tendency'), ('pcod', 'hormonal metabolic imbalance'), ('pcos', 'hormonal metabolic imbalance')]:
        if kw in disease:
            factors['metabolic'].append(phrase)
            break
    if 'high stress' in stress:
        factors['stress_sleep'].append('high psychological stress burden')
    elif 'moderate stress' in stress:
        factors['stress_sleep'].append('moderate stress accumulation')
    if 'poor sleep' in sleep_p:
        factors['stress_sleep'].append('persistently poor sleep quality')
    elif 'irregular sleep' in sleep_p:
        factors['stress_sleep'].append('irregular and disrupted sleep patterns')
    for kw, phrase in [('anxiety', 'anxiety-related nervous system activation'), ('depression', 'depressive mood burden'), ('insomnia', 'clinical insomnia presentation'), ('burnout', 'burnout and exhaustion indicators'), ('ptsd', 'trauma-related stress responses')]:
        if kw in disease:
            factors['stress_sleep'].append(phrase)
            break
    if 'kapha' in prakriti:
        factors['constitution'].append('Kapha-dominant constitution (tendency toward sluggish metabolism)')
    elif 'vata' in prakriti:
        factors['constitution'].append('Vata-dominant constitution (tendency toward nervous depletion)')
    elif 'pitta' in prakriti:
        factors['constitution'].append('Pitta-dominant constitution (tendency toward inflammatory excess)')
    if 'kapha' in nadi and 'kapha' not in prakriti:
        factors['constitution'].append('Kapha Nadi reading indicating current metabolic sluggishness')
    elif 'vata' in nadi and 'vata' not in prakriti:
        factors['constitution'].append('Vata Nadi reading indicating current nervous instability')
    elif 'pitta' in nadi and 'pitta' not in prakriti:
        factors['constitution'].append('Pitta Nadi reading indicating current inflammatory tendency')
    if age in ('41-60', '61+', '61-80'):
        factors['constitution'].append(f'age-related wellness considerations ({age} age group)')
    if 'severe' in severity or 'high' in severity:
        factors['severity'].append('severe symptom presentation requiring active management')
    elif 'moderate' in severity:
        factors['severity'].append('moderate symptom burden requiring systematic care')
    elif 'mild' in severity:
        factors['severity'].append('mild symptom profile with preventive potential')
    for kw, phrase in [('arthritis', 'arthritic inflammation and joint degeneration'), ('rheumatoid', 'rheumatoid autoimmune joint involvement'), ('osteoarthritis', 'degenerative joint wear patterns'), ('gout', 'uric acid crystal deposition in joints'), ('spondylitis', 'spinal inflammatory changes'), ('back pain', 'chronic back pain and postural strain'), ('fibromyalgia', 'widespread musculoskeletal pain sensitization'), ('joint pain', 'persistent joint pain and reduced mobility'), ('sciatica', 'sciatic nerve compression and radiating pain')]:
        if kw in disease:
            factors['joint'].append(phrase)
            break
    for kw, phrase in [('chronic fatigue', 'chronic fatigue syndrome indicators'), ('anaemi', 'haematological deficiency (anaemia)'), ('anemia', 'haematological deficiency (anaemia)'), ('low immunity', 'compromised immune defence capacity'), ('recurrent infection', 'recurrent infectious susceptibility'), ('weakness', 'generalised weakness and low vitality'), ('autoimmune', 'autoimmune dysregulation')]:
        if kw in disease:
            factors['immune'].append(phrase)
            break
    for kw, phrase in [('ibs', 'irritable bowel syndrome disruption'), ('gastritis', 'gastric mucosal inflammation'), ('gerd', 'gastroesophageal reflux disorder'), ('acid reflux', 'chronic acid reflux imbalance'), ('constipation', 'bowel motility impairment'), ('fatty liver', 'hepatic lipid accumulation'), ('indigestion', 'chronic indigestion and digestive weakness'), ('colitis', 'colonic inflammatory patterns'), ('bloating', 'persistent abdominal bloating and gas accumulation'), ('dyspepsia', 'functional dyspepsia and epigastric discomfort')]:
        if kw in disease:
            factors['digestive'].append(phrase)
            break
    for kw, phrase in [('asthma', 'bronchial hypersensitivity (asthma)'), ('copd', 'chronic obstructive pulmonary impairment'), ('bronchitis', 'bronchial inflammatory changes'), ('sinusitis', 'chronic sinus congestion and inflammation'), ('pneumonia', 'pulmonary infectious burden'), ('sleep apn', 'sleep apnoea-related respiratory interruption')]:
        if kw in disease:
            factors['respiratory'].append(phrase)
            break
    return factors
_INTROS = ["The patient's wellness profile reflects", 'Clinical wellness indicators highlight', "The assessment of this patient's health profile reveals", 'Observed wellness patterns in this patient indicate', "The patient's holistic health presentation suggests", 'Integrated clinical indicators point toward', "The patient's Ayurvedic wellness assessment identifies"]
_CONNECTORS = ['combined with', 'alongside', 'in conjunction with', 'compounded by', 'associated with', 'further supported by', 'co-occurring with']
_STRENGTHENERS = ['The recommendation is further strengthened by', 'Primary contributing wellness indicators include', 'The assessment is primarily anchored in', 'Key driving factors for this recommendation include', 'This clinical direction is reinforced by']
_HERBAL_CONCLUSIONS = {'Metabolic Balance Support': ['supporting a metabolism-focused Ayurvedic herbal strategy.', 'indicating the priority of metabolic regulation through targeted herbal support.', 'aligning with a Kapha-pacifying, metabolism-balancing herbal protocol.', 'suggesting a herbal strategy centred on blood sugar, weight, and metabolic stability.'], 'Stress-Relief Herbal Support': ['indicating the need for nervine and adaptogenic herbal support.', 'supporting a stress-relief and nervous system restoration herbal strategy.', 'suggesting Vata-calming, adaptogenic herbal care as the primary approach.', 'aligning with a herbal protocol focused on psychological resilience and sleep restoration.'], 'Digestive Herbal Support': ['suggesting a digestive wellness-oriented Ayurvedic herbal protocol.', 'indicating the priority of gut flora restoration and digestive fire (Agni) correction.', 'supporting herbal care focused on gastric integrity and bowel regularity.', 'aligning with a Pitta-pacifying, digestive herbal management plan.'], 'Immunity Enhancement Support': ['supporting an immunity-enhancement and vitality restoration herbal strategy.', 'indicating the need for Rasayana (rejuvenating) Ayurvedic herbal intervention.', 'suggesting immune-modulating and energy-restoring herbal support as the focus.', 'aligning with an herbal protocol prioritising Ojas (vital essence) replenishment.'], 'Anti-inflammatory Herbal Support': ['indicating the priority of anti-inflammatory and joint-protective herbal management.', 'supporting a Vata-Pitta-pacifying, anti-inflammatory herbal strategy.', 'suggesting targeted herbal support for musculoskeletal inflammation and pain relief.', 'aligning with an herbal protocol centred on reducing systemic inflammatory burden.']}
_LIFESTYLE_CONCLUSIONS = {'Stress Reduction Lifestyle': ['indicating a stress-reduction and nervous system rehabilitation lifestyle approach.', 'supporting a lifestyle framework centred on psychological restoration and calm.', 'aligning with a Vata-balancing, stress-reduction daily wellness protocol.', 'suggesting prioritisation of mental health, sleep hygiene, and nervous system recovery.'], 'Weight Management Lifestyle': ['supporting a structured weight and metabolic management lifestyle programme.', 'indicating the priority of sustainable dietary modification and metabolic rebalancing.', 'aligning with a Kapha-reducing, weight management-oriented lifestyle protocol.', 'suggesting an integrated lifestyle approach to metabolic stabilisation and weight care.'], 'Sleep Improvement Lifestyle': ['indicating the priority of circadian rhythm restoration and sleep quality improvement.', 'supporting a lifestyle framework focused on sleep hygiene and nervous system restoration.', 'suggesting a structured approach to normalising sleep architecture and evening routines.', 'aligning with a Vata-calming, sleep-restorative daily wellness practice.'], 'Active Lifestyle Promotion': ['supporting a gradual, progressive physical activity promotion lifestyle strategy.', 'indicating the priority of overcoming sedentary patterns through structured movement.', 'aligning with an active wellness framework to improve metabolic and cardiovascular health.', 'suggesting a supervised physical rehabilitation and active living lifestyle protocol.'], 'Preventive Wellness Lifestyle': ['supporting a preventive wellness maintenance lifestyle approach.', 'indicating a stable health baseline amenable to proactive Ayurvedic wellness care.', 'aligning with a Dinacharya-based preventive wellness and longevity lifestyle protocol.', 'suggesting a health optimisation and disease prevention lifestyle strategy.']}
_YOGA_CONCLUSIONS = {'Stress Reduction Yoga': ['supporting a calming, Vata-pacifying yoga and meditation therapeutic programme.', 'indicating the priority of nervous system deactivation through restorative yoga practice.', 'aligning with a yoga protocol focused on cortisol reduction and parasympathetic activation.', 'suggesting therapeutic yoga centred on mind-body stress regulation and emotional balance.'], 'Respiratory Pranayama': ['supporting a pranayama and respiratory capacity restoration therapeutic protocol.', 'indicating the priority of airway management and lung function improvement through yoga.', 'aligning with a Kapha-clearing, respiratory pranayama therapeutic programme.', 'suggesting structured breathing therapy to restore pulmonary function and oxygen capacity.'], 'Weight Management Yoga': ['supporting an active, metabolic-stimulating yoga therapeutic programme.', 'indicating the priority of Agni (metabolic fire) activation through dynamic yoga practice.', 'aligning with a Kapha-reducing, calorie-expenditure yoga therapeutic protocol.', 'suggesting a structured yoga programme to improve insulin sensitivity and body composition.'], 'Flexibility & Mobility Therapy': ['supporting a joint-specific flexibility and mobility restoration yoga therapy.', 'indicating the priority of synovial fluid circulation and joint lubrication through yoga.', 'aligning with a Vata-pacifying, joint-protective therapeutic yoga and mobility protocol.', 'suggesting targeted yoga therapy for pain reduction, range of motion, and postural correction.'], 'Relaxation & Sleep Therapy': ['supporting a Yoga Nidra-based deep relaxation and sleep restoration therapeutic protocol.', 'indicating the priority of nervous system deceleration through restorative yoga practice.', 'aligning with a parasympathetic-activation yoga protocol for sleep and recovery.', 'suggesting a therapeutic yoga programme centred on deep rest, restoration, and sleep quality.']}
_FOLLOWUP_CONCLUSIONS = {'Immediate Consultation Recommended': ['indicating an urgent need for immediate medical evaluation and clinical intervention.', "suggesting that the patient's risk profile requires same-day physician assessment.", 'supporting escalation to immediate clinical care given the severity of risk indicators.', 'indicating that the current health parameters necessitate immediate professional review.'], 'Follow-up after 7 Days': ['supporting a close 7-day follow-up to monitor treatment response and risk stabilisation.', 'indicating the need for near-term clinical review within one week.', 'suggesting active monitoring with a structured 7-day reassessment appointment.', 'supporting weekly follow-up to track high-risk clinical indicators.'], 'Follow-up after 15 Days': ['indicating a 15-day follow-up to assess treatment adherence and clinical progress.', 'supporting a fortnightly review to monitor moderate-risk health indicators.', 'suggesting biweekly reassessment to evaluate therapeutic response.', 'aligning with a 15-day clinical monitoring plan for moderate health risk management.'], 'Follow-up after 1 Month': ['supporting a 1-month routine follow-up to evaluate wellness progress.', 'indicating a monthly review for stable moderate-risk clinical monitoring.', 'suggesting a 30-day reassessment for mild-to-moderate health management.', 'aligning with a monthly wellness review plan for ongoing care optimisation.'], 'Regular Wellness Follow-up': ['supporting a standard preventive wellness check-up schedule.', 'indicating a stable health profile appropriate for routine periodic review.', 'aligning with a preventive health monitoring protocol for low-risk wellness management.', 'suggesting standard annual or biannual wellness assessments for health optimisation.']}

def generate_clinical_reasoning(input_data: dict, raw_labels: dict) -> dict:
    """
    Generate dynamic AI-style clinical reasoning for all 4 predicted outputs.

    Parameters
    ----------
    input_data  : dict of 12 patient input features (same keys as ML model)
    raw_labels  : dict of {output_column: predicted_class_string}

    Returns
    -------
    dict with keys: 'herbal', 'lifestyle', 'yoga', 'followup'
    Each value is a multi-sentence natural language reasoning string.

    HOW VARIATION IS ACHIEVED:
    1. Factor extraction: reads actual patient values to build a list of
       specific clinical findings (e.g. "elevated BP 135/88 mmHg", "Kapha
       dominance"). Different patients have different factors.
    2. Phrase selection: intro, connector, and conclusion are drawn from
       pools of 5–7 options using a per-patient deterministic seed. Same
       patient → same phrasing. Different patients → naturally varied output.
    3. Sentence construction: factors are joined with varied connectors,
       producing sentences that read as clinically reasoned narratives.

    NO ML IS INVOLVED. Predictions are unaffected by this function.
    Calling or not calling this function does not change any metric.
    """
    seed = _patient_seed(input_data)
    random = Random(seed)
    factors = _extract_wellness_factors(input_data)
    herbal_class = raw_labels.get('Herbal Therapy Strategy', 'Metabolic Balance Support')
    lifestyle_class = raw_labels.get('Lifestyle Recommendations', 'Preventive Wellness Lifestyle')
    yoga_class = raw_labels.get('Therapeutic Yoga Module', 'Stress Reduction Yoga')
    followup_class = raw_labels.get('Follow-up Recommendation', 'Regular Wellness Follow-up')

    def _join_factors(factor_lists: list, max_factors: int=3) -> list:
        """
        Pull from multiple factor category lists, deduplicate, and cap at max.
        Returns a flat list of factor phrases in a naturally varied order.
        """
        combined = []
        for lst in factor_lists:
            combined.extend(lst)
        combined = list(dict.fromkeys(combined))
        if len(combined) > max_factors:
            step = max(1, len(combined) // max_factors)
            combined = [combined[i] for i in range(0, len(combined), step)][:max_factors]
        return combined

    def _build_sentence(intro: str, factor_list: list, conclusion: str, strengthener: str='', strengthener_factors: list=None) -> str:
        """
        Construct a 1–2 sentence reasoning string.

        Sentence 1: INTRO + up to 3 factors joined by connectors + CONCLUSION
        Sentence 2 (optional): STRENGTHENER + additional context factors

        Example output:
          "The patient's wellness profile reflects Kapha dominance, elevated
          blood pressure, and a sedentary physical activity pattern, supporting
          a metabolism-focused Ayurvedic herbal strategy. The recommendation
          is further strengthened by significant weight excess and moderate
          symptom burden."
        """
        if not factor_list:
            return f'{intro} a complex multi-domain wellness presentation, {conclusion}'
        connector = random.choice(_CONNECTORS)
        if len(factor_list) == 1:
            main = f'{intro} {factor_list[0]}, {conclusion}'
        elif len(factor_list) == 2:
            main = f'{intro} {factor_list[0]} {connector} {factor_list[1]}, {conclusion}'
        else:
            main = f'{intro} {factor_list[0]}, {factor_list[1]}, {connector} {factor_list[2]}, {conclusion}'
        if strengthener and strengthener_factors:
            extra = f' {strengthener} {' and '.join(strengthener_factors[:2])}.'
            return main + extra
        return main
    herbal_factor_priority = {'Metabolic Balance Support': ['metabolic', 'constitution', 'severity'], 'Stress-Relief Herbal Support': ['stress_sleep', 'constitution', 'severity'], 'Digestive Herbal Support': ['digestive', 'constitution', 'severity'], 'Immunity Enhancement Support': ['immune', 'constitution', 'stress_sleep'], 'Anti-inflammatory Herbal Support': ['joint', 'severity', 'constitution']}
    h_priority = herbal_factor_priority.get(herbal_class, ['metabolic', 'constitution', 'severity'])
    h_factors = _join_factors([factors[k] for k in h_priority], max_factors=3)
    h_extra = _join_factors([factors[k] for k in ['severity', 'stress_sleep'] if k not in h_priority], max_factors=2)
    herbal_reasoning = _build_sentence(intro=random.choice(_INTROS), factor_list=h_factors, conclusion=random.choice(_HERBAL_CONCLUSIONS.get(herbal_class, ['requiring targeted herbal care.'])), strengthener=random.choice(_STRENGTHENERS) if h_extra else '', strengthener_factors=h_extra)
    lifestyle_factor_priority = {'Stress Reduction Lifestyle': ['stress_sleep', 'constitution', 'severity'], 'Weight Management Lifestyle': ['metabolic', 'constitution', 'severity'], 'Sleep Improvement Lifestyle': ['stress_sleep', 'constitution', 'metabolic'], 'Active Lifestyle Promotion': ['metabolic', 'joint', 'constitution'], 'Preventive Wellness Lifestyle': ['constitution', 'severity', 'metabolic']}
    l_priority = lifestyle_factor_priority.get(lifestyle_class, ['metabolic', 'constitution', 'severity'])
    l_factors = _join_factors([factors[k] for k in l_priority], max_factors=3)
    l_extra = _join_factors([factors['immune'], factors['digestive']], max_factors=1)
    lifestyle_reasoning = _build_sentence(intro=random.choice(_INTROS), factor_list=l_factors, conclusion=random.choice(_LIFESTYLE_CONCLUSIONS.get(lifestyle_class, ['requiring lifestyle modification.'])), strengthener=random.choice(_STRENGTHENERS) if l_extra else '', strengthener_factors=l_extra)
    yoga_factor_priority = {'Stress Reduction Yoga': ['stress_sleep', 'constitution', 'severity'], 'Respiratory Pranayama': ['respiratory', 'constitution', 'metabolic'], 'Weight Management Yoga': ['metabolic', 'constitution', 'severity'], 'Flexibility & Mobility Therapy': ['joint', 'severity', 'constitution'], 'Relaxation & Sleep Therapy': ['stress_sleep', 'immune', 'constitution']}
    y_priority = yoga_factor_priority.get(yoga_class, ['metabolic', 'constitution', 'severity'])
    y_factors = _join_factors([factors[k] for k in y_priority], max_factors=3)
    yoga_reasoning = _build_sentence(intro=random.choice(_INTROS), factor_list=y_factors, conclusion=random.choice(_YOGA_CONCLUSIONS.get(yoga_class, ['requiring yoga therapeutic support.'])))
    f_factors = _join_factors([factors['metabolic'], factors['severity'], factors['stress_sleep']], max_factors=3)
    followup_reasoning = _build_sentence(intro=random.choice(_INTROS), factor_list=f_factors, conclusion=random.choice(_FOLLOWUP_CONCLUSIONS.get(followup_class, ['requiring clinical follow-up.'])))
    return {'herbal': herbal_reasoning, 'lifestyle': lifestyle_reasoning, 'yoga': yoga_reasoning, 'followup': followup_reasoning}
