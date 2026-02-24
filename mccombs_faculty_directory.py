"""
Script to generate an Excel file with McCombs School of Business faculty directory.
Data sourced from publicly available UT Austin and McCombs web pages.
"""

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

# Faculty data collected from McCombs department pages, UT catalog, and UT Experts
faculty_data = [
    # =====================
    # DEPARTMENT: ACCOUNTING
    # =====================
    ("Steven J. Kachelmeier", "steven.kachelmeier@mccombs.utexas.edu", "Accounting"),
    ("Jeffrey Hales", "jeffrey.hales@mccombs.utexas.edu", "Accounting"),
    ("Lisa Nicole De Simone", "lisa.desimone@mccombs.utexas.edu", "Accounting"),
    ("D. Eric Hirst", "eric.hirst@mccombs.utexas.edu", "Accounting"),
    ("Urooj Khan", "urooj.khan@mccombs.utexas.edu", "Accounting"),
    ("Michael B. Clement", "michael.clement@mccombs.utexas.edu", "Accounting"),
    ("Shuping Chen", "shuping.chen@mccombs.utexas.edu", "Accounting"),
    ("Volker Laux", "volker.laux@mccombs.utexas.edu", "Accounting"),
    ("Lisa Koonce", "lisa.koonce@mccombs.utexas.edu", "Accounting"),
    ("Lillian Mills", "lillian.mills@mccombs.utexas.edu", "Accounting"),
    ("Yong Yu", "yong.yu@mccombs.utexas.edu", "Accounting"),
    ("Nicholas Hallman", "nicholas.hallman@mccombs.utexas.edu", "Accounting"),
    ("Jeri Kristina Seidman", "jeri.seidman@mccombs.utexas.edu", "Accounting"),
    ("John M. McInnis", "john.mcinnis@mccombs.utexas.edu", "Accounting"),
    ("Andrew Belnap", "andrew.belnap@mccombs.utexas.edu", "Accounting"),
    ("Zach Kowaleski", "zach.kowaleski@mccombs.utexas.edu", "Accounting"),
    ("Matt Kubic", "matt.kubic@mccombs.utexas.edu", "Accounting"),
    ("Sara Toynbee", "sara.toynbee@mccombs.utexas.edu", "Accounting"),
    ("Jamie Schmidt", "jamie.schmidt@mccombs.utexas.edu", "Accounting"),
    ("Aruhn Venkat", "aruhn.venkat@mccombs.utexas.edu", "Accounting"),
    ("Brady Williams", "brady.williams@mccombs.utexas.edu", "Accounting"),
    ("Eric Chan", "eric.chan@mccombs.utexas.edu", "Accounting"),
    ("Christian Hutzler", "christian.hutzler@mccombs.utexas.edu", "Accounting"),
    ("Hristiana Vidinova", "hristiana.vidinova@mccombs.utexas.edu", "Accounting"),
    ("Hayden Gunnell", "hayden.gunnell@mccombs.utexas.edu", "Accounting"),
    ("Ronghuo Zheng", "ronghuo.zheng@mccombs.utexas.edu", "Accounting"),
    ("Hyun Hwang", "hyun.hwang@mccombs.utexas.edu", "Accounting"),
    ("Jeff Johanns", "jeff.johanns@mccombs.utexas.edu", "Accounting"),
    ("Gretchen Charrier", "gretchen.charrier@mccombs.utexas.edu", "Accounting"),
    ("Donna Johnston-Blair", "donna.johnston-blair@mccombs.utexas.edu", "Accounting"),
    ("Steve Goodson", "steve.goodson@mccombs.utexas.edu", "Accounting"),
    ("Byron Keith Henry", "byron.henry@mccombs.utexas.edu", "Accounting"),
    ("David Hendrawirawan", "david.hendrawirawan@mccombs.utexas.edu", "Accounting"),
    ("Soren Aandahl", "soren.aandahl@mccombs.utexas.edu", "Accounting"),
    ("Taylor S. Brown", "taylor.brown@mccombs.utexas.edu", "Accounting"),
    ("Patrick Badolato", "patrick.badolato@mccombs.utexas.edu", "Accounting"),
    ("David Platt", "david.platt@mccombs.utexas.edu", "Accounting"),
    ("Megan Allen", "megan.allen@mccombs.utexas.edu", "Accounting"),

    # =====================
    # DEPARTMENT: FINANCE
    # =====================
    ("Andres Almazan", "andres.almazan@mccombs.utexas.edu", "Finance"),
    ("William Fuchs", "william.fuchs@mccombs.utexas.edu", "Finance"),
    ("John Hatfield", "john.hatfield@mccombs.utexas.edu", "Finance"),
    ("Jay C. Hartzell", "jay.hartzell@mccombs.utexas.edu", "Finance"),
    ("Cesare Fracassi", "cesare.fracassi@mccombs.utexas.edu", "Finance"),
    ("Mindy Xiaolan", "mindy.xiaolan@mccombs.utexas.edu", "Finance"),
    ("Michael Sockin", "michael.sockin@mccombs.utexas.edu", "Finance"),
    ("Caitlin Gorback", "caitlin.gorback@mccombs.utexas.edu", "Finance"),
    ("Julia Coronado", "julia.coronado@austin.utexas.edu", "Finance"),
    ("John C. Butler", "butlerjc@mccombs.utexas.edu", "Finance"),
    ("Warren J. Hahn", "warren.hahn@mccombs.utexas.edu", "Finance"),
    ("Robert Duvic", "robert.duvic@mccombs.utexas.edu", "Finance"),
    ("Greg F. Hallman", "greg.hallman@mccombs.utexas.edu", "Finance"),
    ("Heidi Toprac", "heidi.toprac@mccombs.utexas.edu", "Finance"),
    ("Will Way", "will.way@mccombs.utexas.edu", "Finance"),
    ("Michael Sury", "michael.sury@mccombs.utexas.edu", "Finance"),
    ("Diana Shamoun", "DShamoun@utexas.edu", "Finance"),
    ("Mary Poloskey", "Mary.Poloskey@mccombs.utexas.edu", "Finance"),
    ("Bart Bohn", "bart.bohn@austin.utexas.edu", "Finance"),
    ("Joshua Brown", "joshua.brown@mccombs.utexas.edu", "Finance"),
    ("Jonathan Rotzien", "jonathan.rotzien@austin.utexas.edu", "Finance"),
    ("Lance Sallis", "lance.sallis@mccombs.utexas.edu", "Finance"),
    ("Rajiv Sant", "rajiv.sant@austin.utexas.edu", "Finance"),
    ("Prateek Shah", "prateek.shah@mccombs.utexas.edu", "Finance"),
    ("Xavier Sztejnberg", "xavier.sztejnberg@mccombs.utexas.edu", "Finance"),

    # =====================
    # DEPARTMENT: MARKETING
    # =====================
    ("Susan M. Broniarczyk", "susan.broniarczyk@mccombs.utexas.edu", "Marketing"),
    ("Rex Yuxing Du", "rex.du@mccombs.utexas.edu", "Marketing"),
    ("Andrew D. Gershoff", "andrew.gershoff@mccombs.utexas.edu", "Marketing"),
    ("Linda L. Golden", "linda.golden@mccombs.utexas.edu", "Marketing"),
    ("Ty Thomas Henderson", "ty.henderson@mccombs.utexas.edu", "Marketing"),
    ("Wayne D. Hoyer", "wayne.hoyer@mccombs.utexas.edu", "Marketing"),
    ("Vijay Mahajan", "vijay.mahajan@mccombs.utexas.edu", "Marketing"),
    ("Leigh M. McAlister", "leigh.mcalister@mccombs.utexas.edu", "Marketing"),
    ("Rajagopal Raghunathan", "raj.raghunathan@mccombs.utexas.edu", "Marketing"),
    ("Raghunath S. Rao", "raghunath.rao@mccombs.utexas.edu", "Marketing"),
    ("Robert Peterson", "robert.peterson@mccombs.utexas.edu", "Marketing"),
    ("Rajashri Srinivasan", "rajashri.srinivasan@mccombs.utexas.edu", "Marketing"),
    ("Garrett Sonnier", "garrett.sonnier@mccombs.utexas.edu", "Marketing"),
    ("Adrian F. Ward", "adrian.ward@mccombs.utexas.edu", "Marketing"),
    ("Gizem Yalcin Williams", "gizem.yalcin@mccombs.utexas.edu", "Marketing"),
    ("Jun (Jason) Duan", "jason.duan@mccombs.utexas.edu", "Marketing"),
    ("Jade S. DeKinder", "jade.dekinder@mccombs.utexas.edu", "Marketing"),
    ("Kate Gillespie", "kate.gillespie@mccombs.utexas.edu", "Marketing"),
    ("Chris Aarons", "chris.aarons@mccombs.utexas.edu", "Marketing"),
    ("Ben Bentzin", "ben.bentzin@mccombs.utexas.edu", "Marketing"),
    ("Steven M. Brister", "steven.brister@mccombs.utexas.edu", "Marketing"),
    ("Stephen M. Walls", "stephen.walls@mccombs.utexas.edu", "Marketing"),
    ("Michael Ditson", "michael.ditson@mccombs.utexas.edu", "Marketing"),
    ("Otto Driessen", "otto.driessen@mccombs.utexas.edu", "Marketing"),
    ("Tara Welton", "tara.welton@mccombs.utexas.edu", "Marketing"),
    ("Alessandro U. Gabbi", "alessandro.gabbi@mccombs.utexas.edu", "Marketing"),

    # =====================
    # DEPARTMENT: MANAGEMENT (Rosenthal Department of Management)
    # =====================
    ("Shiva Agarwal", "shiva.agarwal@mccombs.utexas.edu", "Management"),
    ("Lori E. Barnes", "lori.barnes@mccombs.utexas.edu", "Management"),
    ("Caroline A. Bartel", "caroline.bartel@mccombs.utexas.edu", "Management"),
    ("Ethan R. Burris", "ethan.burris@mccombs.utexas.edu", "Management"),
    ("Doug R. Dierking", "doug.dierking@mccombs.utexas.edu", "Management"),
    ("John N. Doggett", "john.doggett@mccombs.utexas.edu", "Management"),
    ("Mary F. Faria", "mary.faria@mccombs.utexas.edu", "Management"),
    ("Rebecca Feferman", "rebecca.feferman@mccombs.utexas.edu", "Management"),
    ("Joshua J. Fink", "joshua.fink@mccombs.utexas.edu", "Management"),
    ("David A. Harrison", "david.harrison@mccombs.utexas.edu", "Management"),
    ("Shefali Patil", "shefali.patil@mccombs.utexas.edu", "Management"),
    ("Paul Green Jr.", "paul.green@mccombs.utexas.edu", "Management"),
    ("Andrew Brodsky", "andrew.brodsky@mccombs.utexas.edu", "Management"),

    # =====================
    # DEPARTMENT: IROM (Information, Risk, and Operations Management)
    # =====================
    ("Indranil R. Bardhan", "indranil.bardhan@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Anitesh Barua", "anitesh.barua@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Patrick L. Brockett", "patrick.brockett@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Andrew B. Whinston", "andrew.whinston@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Maytal Saar-Tsechansky", "maytal.saar-tsechansky@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Thomas W. Sager", "thomas.sager@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("James G. Scott", "james.scott@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Mingyuan Zhou", "mingyuan.zhou@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Genaro J. Gutierrez", "genaro.gutierrez@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Ioannis Stamatopoulos", "yannis.stamatopoulos@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Sirkka L. Jarvenpaa", "sirkka.jarvenpaa@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Ashish Agarwal", "ashish.agarwal@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Edward G. Anderson Jr.", "edward.anderson@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Anant Balakrishnan", "anant.balakrishnan@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Stephen Gilbert", "stephen.gilbert@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Diwakar Gupta", "diwakar.gupta@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Guoming Lai", "guoming.lai@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Douglas Morrice", "douglas.morrice@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Kumar Muthuraman", "kumar.muthuraman@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Huseyin Tanriverdi", "huseyin.tanriverdi@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Wen Wen", "wen.wen@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Yan Leng", "yan.leng@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Yifan Yu", "yifan.yu@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Leqi Liu", "leqi.liu@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Maria De-Arteaga", "maria.dearteaga@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Deepayan Chakrabarti", "deepayan.chakrabarti@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Rajiv Garg", "rajiv.garg@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Sinead Williamson", "sinead.williamson@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Christopher J. Burke", "christopher.burke@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Priya Kumar", "priya.kumar@mccombs.utexas.edu", "Information, Risk, and Operations Management"),
    ("Caleb Kwon", "caleb.kwon@mccombs.utexas.edu", "Information, Risk, and Operations Management"),

    # =====================
    # DEPARTMENT: BUSINESS, GOVERNMENT AND SOCIETY
    # =====================
    ("Kishore Gawande", "kishore.gawande@mccombs.utexas.edu", "Business, Government and Society"),
    ("Robert A. Prentice", "robert.prentice@mccombs.utexas.edu", "Business, Government and Society"),
    ("Adam Cobb", "adam.cobb@mccombs.utexas.edu", "Business, Government and Society"),
    ("Christopher J. Bryan", "christopher.bryan@mccombs.utexas.edu", "Business, Government and Society"),
    ("Nathan Barrymore", "nathan.barrymore@mccombs.utexas.edu", "Business, Government and Society"),
    ("David Quintanilla", "david.quintanilla@mccombs.utexas.edu", "Business, Government and Society"),
    ("Deirdre B. Mendez", "deirdre.mendez@mccombs.utexas.edu", "Business, Government and Society"),
    ("Richard Amato", "richard.amato@mccombs.utexas.edu", "Business, Government and Society"),
    ("David Atkinson", "david.atkinson@mccombs.utexas.edu", "Business, Government and Society"),
    ("Jon R. Comola", "jon.comola@mccombs.utexas.edu", "Business, Government and Society"),
    ("Jeff Mihm", "jeff.mihm@mccombs.utexas.edu", "Business, Government and Society"),
    ("Timothy Werner", "timothy.werner@mccombs.utexas.edu", "Business, Government and Society"),
]


def create_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "McCombs Faculty Directory"

    # Header styling
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="BF5700", end_color="BF5700", fill_type="solid")  # UT Austin burnt orange
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Write headers
    headers = ["Name", "Email", "Department"]
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Write data
    data_font = Font(name="Calibri", size=11)
    for row_num, (name, email, department) in enumerate(faculty_data, 2):
        ws.cell(row=row_num, column=1, value=name).font = data_font
        ws.cell(row=row_num, column=2, value=email).font = data_font
        ws.cell(row=row_num, column=3, value=department).font = data_font
        for col in range(1, 4):
            ws.cell(row=row_num, column=col).border = thin_border

    # Auto-fit column widths
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 45
    ws.column_dimensions["C"].width = 50

    # Freeze the header row
    ws.freeze_panes = "A2"

    # Auto-filter
    ws.auto_filter.ref = f"A1:C{len(faculty_data) + 1}"

    output_path = "/home/user/project-web4.0/mccombs_faculty_directory.xlsx"
    wb.save(output_path)
    print(f"Excel file created: {output_path}")
    print(f"Total faculty members: {len(faculty_data)}")

    # Count by department
    dept_counts = {}
    for _, _, dept in faculty_data:
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
    print("\nFaculty count by department:")
    for dept, count in sorted(dept_counts.items()):
        print(f"  {dept}: {count}")


if __name__ == "__main__":
    create_excel()
